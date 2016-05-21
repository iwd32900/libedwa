"""
Encrypted GET and POST data using Keyczar for Event-Driven Web Applications.
"""
from __future__ import absolute_import
import hashlib
from zlib import compress, decompress
from libedwa.core import EDWA, Page, Action, TamperingError

__all__ = ['KeyczarEDWA']

import keyczar.keyczar
class KeyczarEDWA(EDWA):
    HASH_LEN = 32
    def __init__(self, path_to_keys, *args, **kwargs):
        """This version provides excellent security (as far as I know) while still storing all data on the client side.
        Both actions and page states are encrypted, so that clients cannot decode their contents.
        However, it is very, very slow compared to the unencrypted version -- generating 100 links takes several seconds.
        Also, the action IDs (passed in URLs) are ~50% larger, typically 200 - 300 characters."""
        super(KeyczarEDWA, self).__init__("THIS WILL NEVER BE USED", *args, **kwargs)
        del self._secret_key # just to make sure the dummy value is never used
        self.path_to_keys = path_to_keys
        self.crypter = keyczar.keyczar.Crypter.Read(self.path_to_keys)
    def _encode_page(self):
        assert self._curr_page is not None
        self._curr_page_encoded = self.crypter.Encrypt(compress(self._curr_page.encode(), 1)) # also HMAC-SHA1 signed and web-safe base64 encoded
    def _decode_page(self):
        assert self._curr_page_encoded is not None
        self._set_page(Page.decode(decompress(self.crypter.Decrypt(self._curr_page_encoded))))
    def _encode_action(self, action):
        assert self._mode is not EDWA.MODE_ACTION, "Can't create new actions during an action, because page state is not finalized."
        if self._curr_page_encoded is None: self._encode_page() # ensure page has been serialized
        assert self._curr_page_encoded is not None, "Page state must be serialized before creating an action!"
        # Although the action will be encrypted and signed,
        # we have to prevent attackers mixing-and-matching actions with page states.
        page_hash = hashlib.sha256(self._curr_page_encoded).digest()
        assert len(page_hash) == self.HASH_LEN
        return self.crypter.Encrypt(compress(action.encode()+page_hash, 1))
    def _decode_action(self, action_id):
        assert self._curr_page_encoded is not None, "Page state must be known when decoding an action!"
        action_and_hash = decompress(self.crypter.Decrypt(action_id))
        assert len(action_and_hash) >= self.HASH_LEN
        action, page_hash = Action.decode(action_and_hash[:-self.HASH_LEN]), action_and_hash[-self.HASH_LEN:]
        if page_hash != hashlib.sha256(self._curr_page_encoded).digest():
            raise TamperingError("Action and page data were mixed-and-matched for %s" % action_id)
        return action
