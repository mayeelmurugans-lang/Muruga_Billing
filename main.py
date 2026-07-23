"""
main.py -- Kivy front end for the billing app. Same file runs on Windows (via PyInstaller)
and Android (via Buildozer) -- it's the same UI toolkit on both, so there's one codebase to
maintain instead of two.

This is a working starting point, not a pixel-for-pixel port of every screen in the
original Tkinter app. It covers the full end-to-end flow (pick doc type -> fill
company/buyer -> add items -> generate PDF/Excel with synced numbering) so you can run it,
test it, and extend it. Left as clear next steps (see README.md):
  - Saved-profile picker (dropdown of previously used companies/buyers) -- the data is
    already being saved via bc.upsert_profile()/bc.save_profiles(), just not surfaced yet.
  - Logo upload / PDF watermark.
  - Editing a previously generated invoice.

Run on desktop right now with:  pip install kivy && python main.py
"""
import os
import threading
from datetime import datetime

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from kivy.uix.popup import Popup
from kivy.utils import platform
from kivy.clock import Clock

import billing_core as bc
from cloud_sync import CloudCounterClient

# ---- Fill these in after the Firebase setup described in cloud_sync.py ----
FIREBASE_DB_URL = ""      # e.g. "https://guhan-billing-sync-default-rtdb.asia-southeast1.firebasedatabase.app"
FIREBASE_AUTH_SECRET = None

DOC_TYPES = ["Tax Invoice", "Proforma Invoice", "Quotation"]


def make_labeled_input(label_text, height=40):
    row = BoxLayout(orientation="horizontal", size_hint_y=None, height=height, spacing=8)
    row.add_widget(Label(text=label_text, size_hint_x=0.35, halign="right"))
    inp = TextInput(multiline=False, size_hint_x=0.65)
    row.add_widget(inp)
    return row, inp


class StorageChoicePopup(Popup):
    """Shown once at startup on Android: Internal (private, always works, not visible in a
    file manager) vs External (shared storage, visible / shareable, needs a permission on
    some Android versions)."""

    def __init__(self, on_choice, **kwargs):
        super().__init__(title="Where should invoices be saved?", size_hint=(0.85, 0.45), auto_dismiss=False, **kwargs)
        self.on_choice = on_choice
        box = BoxLayout(orientation="vertical", spacing=12, padding=16)
        box.add_widget(Label(
            text="Internal storage is private to this app and always works.\n\n"
                 "External storage saves to shared storage so you can find the\n"
                 "PDF/Excel files from a file manager or share them elsewhere.",
            halign="center",
        ))
        btn_row = BoxLayout(orientation="horizontal", spacing=12, size_hint_y=None, height=50)
        internal_btn = Button(text="Internal storage")
        external_btn = Button(text="External storage")
        internal_btn.bind(on_release=lambda *_: self._choose("internal"))
        external_btn.bind(on_release=lambda *_: self._choose("external"))
        btn_row.add_widget(internal_btn)
        btn_row.add_widget(external_btn)
        box.add_widget(btn_row)
        self.content = box

    def _choose(self, choice):
        self.dismiss()
        self.on_choice(choice)


class ItemRow(BoxLayout):
    """One row in the on-screen item ledger (read-only display + Edit/Delete)."""

    def __init__(self, item, on_edit, on_delete, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height=36, spacing=4, **kwargs)
        text = (f"{item['SI No.']}. {item['Description of Goods']}  x{item['Quantity']} "
                f"{item['Unit']} @ {item['Unit Price']:.2f}  ({item['GST Type']} {item['GST Rate']}%)")
        self.add_widget(Label(text=text, size_hint_x=0.7, shorten=True))
        edit_btn = Button(text="Edit", size_hint_x=0.15)
        del_btn = Button(text="Del", size_hint_x=0.15)
        edit_btn.bind(on_release=lambda *_: on_edit(item))
        del_btn.bind(on_release=lambda *_: on_delete(item))
        self.add_widget(edit_btn)
        self.add_widget(del_btn)


class MainScreen(BoxLayout):
    def __init__(self, cloud_client, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.cloud_client = cloud_client
        self.items = []
        self.editing_item_idx = None

        scroll = ScrollView()
        form = GridLayout(cols=1, size_hint_y=None, spacing=10, padding=10)
        form.bind(minimum_height=form.setter("height"))

        # --- Document type ---
        form.add_widget(Label(text="Document Type", size_hint_y=None, height=24))
        self.doc_type_spinner = Spinner(text=DOC_TYPES[0], values=DOC_TYPES, size_hint_y=None, height=44)
        form.add_widget(self.doc_type_spinner)

        # --- Company info (prefilled from saved profile / DEFAULT_COMPANY) ---
        profiles = bc.load_profiles()
        default_company = profiles["companies"][0] if profiles["companies"] else bc.DEFAULT_COMPANY

        form.add_widget(Label(text="Company", size_hint_y=None, height=28, bold=True))
        row, self.ent_cname = make_labeled_input("Name"); self.ent_cname.text = default_company.get("name", ""); form.add_widget(row)
        row, self.ent_caddr = make_labeled_input("Address"); self.ent_caddr.text = default_company.get("address", ""); form.add_widget(row)
        row, self.ent_cgstin = make_labeled_input("GSTIN"); self.ent_cgstin.text = default_company.get("gstin", ""); form.add_widget(row)
        row, self.ent_ccontact = make_labeled_input("Contact"); self.ent_ccontact.text = default_company.get("contact", ""); form.add_widget(row)
        row, self.ent_cemail = make_labeled_input("Email"); self.ent_cemail.text = default_company.get("email", ""); form.add_widget(row)

        # --- Buyer info ---
        form.add_widget(Label(text="Buyer", size_hint_y=None, height=28, bold=True))
        row, self.ent_bname = make_labeled_input("Name"); form.add_widget(row)
        row, self.ent_baddr = make_labeled_input("Address"); form.add_widget(row)
        row, self.ent_bgstin = make_labeled_input("GSTIN"); form.add_widget(row)
        row, self.ent_bcontact = make_labeled_input("Contact Name"); form.add_widget(row)
        row, self.ent_bmobile = make_labeled_input("Mobile"); form.add_widget(row)

        # --- Item entry ---
        form.add_widget(Label(text="Add Item", size_hint_y=None, height=28, bold=True))
        item_entry_row = GridLayout(cols=2, size_hint_y=None, height=200, spacing=4)
        self.ent_desc = TextInput(hint_text="Description", multiline=True)
        self.ent_hsn = TextInput(hint_text="HSN/SAC")
        self.ent_qty = TextInput(hint_text="Qty", input_filter="int")
        self.unit_spinner = Spinner(text=bc.STANDARD_UNITS[0], values=bc.STANDARD_UNITS)
        self.ent_rate = TextInput(hint_text="Unit Price", input_filter="float")
        self.gst_type_spinner = Spinner(text="GST", values=["GST", "IGST"])
        self.gst_rate_spinner = Spinner(text="18", values=["0", "5", "12", "18", "28"])
        for w in (self.ent_desc, self.ent_hsn, self.ent_qty, self.unit_spinner, self.ent_rate, self.gst_type_spinner, self.gst_rate_spinner):
            item_entry_row.add_widget(w)
        form.add_widget(item_entry_row)

        self.add_item_btn = Button(text="+ Add Row", size_hint_y=None, height=40)
        self.add_item_btn.bind(on_release=self.add_item)
        form.add_widget(self.add_item_btn)

        form.add_widget(Label(text="Items", size_hint_y=None, height=24, bold=True))
        self.items_box = GridLayout(cols=1, size_hint_y=None, spacing=2)
        self.items_box.bind(minimum_height=self.items_box.setter("height"))
        form.add_widget(self.items_box)

        # --- Bank info ---
        form.add_widget(Label(text="Bank Details", size_hint_y=None, height=28, bold=True))
        row, self.ent_bank_name = make_labeled_input("Bank Name"); self.ent_bank_name.text = default_company.get("bank_name", ""); form.add_widget(row)
        row, self.ent_ac_no = make_labeled_input("A/c No"); self.ent_ac_no.text = default_company.get("ac_no", ""); form.add_widget(row)
        row, self.ent_ifsc = make_labeled_input("IFSC"); self.ent_ifsc.text = default_company.get("ifsc", ""); form.add_widget(row)

        # --- Terms ---
        form.add_widget(Label(text="Terms and Conditions (one per line)", size_hint_y=None, height=24, bold=True))
        self.txt_terms = TextInput(
            text="Payment due within 15 days.\nGoods once sold will not be taken back.",
            size_hint_y=None, height=100, multiline=True,
        )
        form.add_widget(self.txt_terms)

        # --- Generate ---
        self.status_label = Label(text="", size_hint_y=None, height=30)
        form.add_widget(self.status_label)
        generate_btn = Button(text="Generate & Save", size_hint_y=None, height=50)
        generate_btn.bind(on_release=self.generate)
        form.add_widget(generate_btn)

        scroll.add_widget(form)
        self.add_widget(scroll)

    # ---- item ledger ----
    def add_item(self, *_):
        desc = self.ent_desc.text.strip()
        hsn = self.ent_hsn.text.strip()
        qty_str = self.ent_qty.text.strip()
        rate_str = self.ent_rate.text.strip()
        if not (desc and hsn and qty_str and rate_str):
            self.status_label.text = "Fill in all item fields first."
            return
        try:
            qty = int(qty_str)
            rate = float(rate_str)
            gst_rate = float(self.gst_rate_spinner.text)
        except ValueError:
            self.status_label.text = "Qty/Rate/GST rate must be numbers."
            return

        item = {
            "SI No.": len(self.items) + 1,
            "Description of Goods": desc,
            "HSN/SAC": hsn,
            "Quantity": qty,
            "Unit": self.unit_spinner.text,
            "Unit Price": rate,
            "GST Type": self.gst_type_spinner.text,
            "GST Rate": gst_rate,
        }
        if self.editing_item_idx is not None:
            item["SI No."] = self.items[self.editing_item_idx]["SI No."]
            self.items[self.editing_item_idx] = item
            self.editing_item_idx = None
            self.add_item_btn.text = "+ Add Row"
        else:
            self.items.append(item)
        self.refresh_items_box()
        self.ent_desc.text = self.ent_hsn.text = self.ent_qty.text = self.ent_rate.text = ""

    def refresh_items_box(self):
        self.items_box.clear_widgets()
        for item in self.items:
            self.items_box.add_widget(ItemRow(item, self.edit_item, self.delete_item))

    def edit_item(self, item):
        idx = self.items.index(item)
        self.editing_item_idx = idx
        self.ent_desc.text = item["Description of Goods"]
        self.ent_hsn.text = item["HSN/SAC"]
        self.ent_qty.text = str(item["Quantity"])
        self.ent_rate.text = str(item["Unit Price"])
        self.unit_spinner.text = item["Unit"]
        self.gst_type_spinner.text = item["GST Type"]
        rate_val = item["GST Rate"]
        self.gst_rate_spinner.text = str(int(rate_val)) if float(rate_val).is_integer() else str(rate_val)
        self.add_item_btn.text = "Update Row"

    def delete_item(self, item):
        self.items.remove(item)
        for i, it in enumerate(self.items):
            it["SI No."] = i + 1
        self.refresh_items_box()

    # ---- generate ----
    def generate(self, *_):
        if not self.items:
            self.status_label.text = "Add at least one item first."
            return

        doc_type = self.doc_type_spinner.text
        company_info = {
            "name": self.ent_cname.text.strip(), "address": self.ent_caddr.text.strip(),
            "gstin": self.ent_cgstin.text.strip(), "contact": self.ent_ccontact.text.strip(),
            "email": self.ent_cemail.text.strip(), "logo_path": "",
        }
        buyer_info = {
            "name": self.ent_bname.text.strip(), "address": self.ent_baddr.text.strip(),
            "gstin": self.ent_bgstin.text.strip(), "contact_name": self.ent_bcontact.text.strip(),
            "mobile": self.ent_bmobile.text.strip(),
        }
        bank_info = {
            "bank_name": self.ent_bank_name.text.strip(), "ac_no": self.ent_ac_no.text.strip(),
            "ifsc": self.ent_ifsc.text.strip(),
        }
        if not company_info["name"] or not company_info["address"] or not buyer_info["name"] or not buyer_info["address"]:
            self.status_label.text = "Company and buyer name/address are required."
            return

        terms = [line.strip() for line in self.txt_terms.text.split("\n") if line.strip()]

        self.status_label.text = "Working..."
        # Off the UI thread, so a slow/offline cloud call doesn't freeze the app.
        threading.Thread(
            target=self._generate_worker,
            args=(doc_type, company_info, buyer_info, bank_info, terms),
            daemon=True,
        ).start()

    def _generate_worker(self, doc_type, company_info, buyer_info, bank_info, terms):
        try:
            client = self.cloud_client if (self.cloud_client and self.cloud_client.is_online()) else None
            inv_str, raw_num, counter_path = bc.get_next_document_number(doc_type, company_info["name"], cloud_client=client)
            meta_info = {
                "invoice_no": inv_str,
                "invoice_date": datetime.now().strftime("%d-%m-%Y"),
                "po_number": "", "po_date": "",
            }
            pdf_path = bc.generate_pdf(doc_type, company_info, buyer_info, bank_info, terms, meta_info, self.items)
            bc.generate_excel(doc_type, company_info, buyer_info, bank_info, terms, meta_info, self.items)
            bc.update_summary_excel(company_info, doc_type, meta_info, buyer_info, self.items)
            bc.update_hsn_summary_excel(company_info, meta_info, self.items)
            bc.save_document_number(counter_path, raw_num)

            profiles = bc.load_profiles()
            bc.upsert_profile(profiles["companies"], "name", dict(company_info, **bank_info))
            bc.upsert_profile(profiles["buyers"], "name", dict(buyer_info))
            bc.save_profiles(profiles)

            msg = f"Saved as {inv_str}\nPDF: {pdf_path}"
        except Exception as e:
            msg = f"Failed: {type(e).__name__}: {e}"

        Clock.schedule_once(lambda dt: setattr(self.status_label, "text", msg))


class BillingApp(App):
    def build(self):
        self.cloud_client = CloudCounterClient(FIREBASE_DB_URL, FIREBASE_AUTH_SECRET) if FIREBASE_DB_URL else None
        root = BoxLayout()

        if platform == "android":
            # Ask Internal vs External storage before building the form.
            def on_choice(choice):
                self._apply_android_storage_choice(choice)
                root.add_widget(MainScreen(self.cloud_client))
            Clock.schedule_once(lambda dt: StorageChoicePopup(on_choice).open(), 0.3)
        else:
            # Desktop/Windows: same behaviour as the original app (data folder next to the program).
            root.add_widget(MainScreen(self.cloud_client))
        return root

    def _apply_android_storage_choice(self, choice):
        from android.storage import app_storage_path, primary_external_storage_path
        if choice == "internal":
            bc.set_base_dir(app_storage_path())
        else:
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE])
            bc.set_base_dir(os.path.join(primary_external_storage_path(), "GuhanBilling"))


if __name__ == "__main__":
    BillingApp().run()
