import os
import sys

if getattr(sys, 'frozen', False):
    try:
        import certifi
        ca_bundle = certifi.where()
        os.environ.setdefault('REQUESTS_CA_BUNDLE', ca_bundle)
        os.environ.setdefault('SSL_CERT_FILE', ca_bundle)
    except Exception:  # pylint: disable=broad-except
        pass
