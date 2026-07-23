"""
cloud_sync.py -- the simplest free way to keep invoice/proforma/quotation numbers in sync
between your Windows PC and an Android phone.

Uses Firebase Realtime Database's plain REST API -- no Firebase SDK, no Google Play
Services, no google-services.json, just HTTPS + the `requests` library. That matters here
because the full Firebase Android SDK is a native Java/Kotlin library and is painful to
wire into a Kivy/Buildozer app; the REST API is just URLs, so it works identically in the
Windows build and the Android build.

--- ONE-TIME SETUP (about 5 minutes, free "Spark" plan, no credit card needed) ---
1. Go to https://console.firebase.google.com -> "Add project" (any name works, e.g.
   "guhan-billing-sync"). Google Analytics is not needed, you can skip it.
2. In the left menu: Build > Realtime Database > "Create Database". Pick the region
   closest to you (e.g. Mumbai/asia-south1 or Singapore/asia-southeast1). Choose
   "Start in test mode" for now (open read/write for 30 days -- fine while you're building
   and testing; see "LOCKING IT DOWN" below before you go live).
3. Copy the URL shown at the top of the Realtime Database page. It looks like:
       https://guhan-billing-sync-default-rtdb.asia-southeast1.firebasedatabase.app
4. Paste that URL wherever you construct CloudCounterClient(...) in main.py.

That's it -- no server, nothing to maintain, and the free tier (1GB storage, 10GB/month
transfer) is enormous overkill for a few KB of invoice counters.

--- LOCKING IT DOWN (do this before real use, test mode expires after 30 days anyway) ---
In Realtime Database > Rules, replace the default with something like:
    {
      "rules": {
        "counters": {
          ".read": "auth != null",
          ".write": "auth != null"
        }
      }
    }
and generate a "Database secret" under Project Settings > Service accounts > Database
secrets (legacy, but simplest for this use case), then pass it as auth_secret below. It
gets appended as ?auth=<secret> on every request -- keep it out of any public repo.

--- HOW THE SYNC WORKS (and its one honest limitation) ---
Each device, when it goes to issue a new document number, asks the cloud for the highest
number seen so far, takes max(cloud, its own local counter) + 1, and writes that back. If
your Windows PC and phone are BOTH offline at the same moment and each independently issue
an invoice, you could get two documents with the same number -- the discrepancy shows up
the next time either device goes online, since the max() bump will skip visibly. For a
small business syncing a laptop and one phone, that's an acceptable trade-off for something
this simple and free; if you need a hard guarantee, that requires a proper backend with
atomic transactions (e.g. Cloud Functions + a Firestore transaction), which is a fair bit
more setup than described here.
"""
import requests


class CloudUnavailable(Exception):
    """Raised when the cloud counter can't be reached or the response can't be trusted.
    billing_core.get_next_document_number() catches this and falls back to the local
    counter file automatically -- callers of reserve_next() should let it propagate."""


class CloudCounterClient:
    def __init__(self, database_url, auth_secret=None, timeout=2.5):
        """
        database_url: your Realtime Database URL from the Firebase console (see setup above).
        auth_secret:  optional Database Secret (see "LOCKING IT DOWN"). Leave as None only
                      while your rules are still wide open in test mode.
        timeout:      seconds to wait before treating the connection as "offline" and
                      letting the caller fall back to local numbering. Kept short (a couple
                      of seconds) so a dead connection doesn't freeze the UI while the user
                      is trying to generate an invoice.
        """
        self.base = database_url.rstrip("/")
        self.auth_secret = auth_secret
        self.timeout = timeout

    def _url(self, path):
        url = f"{self.base}/{path}.json"
        if self.auth_secret:
            url += f"?auth={self.auth_secret}"
        return url

    def is_online(self):
        """Cheap connectivity probe -- call this first so you can show the user an
        Online/Offline indicator instead of only discovering it when Generate is pressed."""
        try:
            requests.get(self._url("_healthcheck"), timeout=self.timeout)
            return True
        except requests.exceptions.RequestException:
            return False

    def reserve_next(self, company_slug, counter_key, local_last):
        """
        Read the current cloud value for counters/{company_slug}/{counter_key}, combine it
        with local_last (whatever this device's own counter file says), take the higher one
        + 1, write that back to the cloud, and return it. Raises CloudUnavailable on any
        network problem so the caller can fall back to local-only numbering.
        """
        path = f"counters/{company_slug}/{counter_key}"
        try:
            resp = requests.get(self._url(path), timeout=self.timeout)
            resp.raise_for_status()
            cloud_val = resp.json()
        except requests.exceptions.RequestException as e:
            raise CloudUnavailable(str(e)) from e

        cloud_val = int(cloud_val) if isinstance(cloud_val, (int, float)) else 0
        baseline = max(cloud_val, local_last or 0, 1022)  # 1022 keeps the same starting point (1023) as the original app
        next_num = baseline + 1

        try:
            put_resp = requests.put(self._url(path), json=next_num, timeout=self.timeout)
            put_resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise CloudUnavailable(str(e)) from e

        return next_num
