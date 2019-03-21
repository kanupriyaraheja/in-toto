#!/usr/bin/env python

"""
<Program Name>
  test_gpg.py

<Author>
  Santiago Torres-Arias <santiago@nyu.edu>
  Lukas Puehringer <lukas.puehringer@nyu.edu>

<Started>
  Nov 15, 2017

<Copyright>
  See LICENSE for licensing information.

<Purpose>
  Test gpg/pgp-related functions.

"""

import os
import shutil
import tempfile
import unittest
from mock import patch
from six import string_types

import cryptography.hazmat.primitives.serialization as serialization
import cryptography.hazmat.backends as backends
import cryptography.hazmat.primitives.hashes as hashing

from in_toto import process
from in_toto.gpg.functions import (gpg_sign_object, gpg_export_pubkey,
    gpg_verify_signature)
from in_toto.gpg.util import (get_version, is_version_fully_supported,
    get_hashing_class, parse_packet_header, parse_subpacket_header)
from in_toto.gpg.rsa import create_pubkey as rsa_create_pubkey
from in_toto.gpg.dsa import create_pubkey as dsa_create_pubkey
from in_toto.gpg.common import (parse_pubkey_payload, parse_pubkey_bundle,
    get_pubkey_bundle)
from in_toto.gpg.constants import (SHA1, SHA256, SHA512,
    GPG_EXPORT_PUBKEY_COMMAND, PACKET_TYPE_PRIMARY_KEY, PACKET_TYPE_USER_ID,
    PACKET_TYPE_USER_ATTR, PACKET_TYPE_SUB_KEY)
from in_toto.gpg.exceptions import (PacketParsingError,
    PacketVersionNotSupportedError, SignatureAlgorithmNotSupportedError,
    KeyNotFoundError)
from in_toto.gpg.formats import PUBKEY_SCHEMA


import securesystemslib.formats
import securesystemslib.exceptions

@unittest.skipIf(os.getenv("TEST_SKIP_GPG"), "gpg not found")
class TestUtil(unittest.TestCase):
  """Test util functions. """
  def test_version_utils_return_types(self):
    """Run dummy tests for coverage. """
    self.assertTrue(isinstance(get_version(), string_types))
    self.assertTrue(isinstance(is_version_fully_supported(), bool))

  def test_get_hashing_class(self):
    # Assert return expected hashing class
    expected_hashing_class = [hashing.SHA1, hashing.SHA256, hashing.SHA512]
    for idx, hashing_id in enumerate([SHA1, SHA256, SHA512]):
      result = get_hashing_class(hashing_id)
      self.assertEqual(result, expected_hashing_class[idx])

    # Assert raises ValueError with non-supported hashing id
    with self.assertRaises(ValueError):
      get_hashing_class("bogus_hashing_id")

  def test_parse_packet_header(self):
    """Test parse_packet_header with manually crafted data. """
    data_list = [
        ## New format packet length with mock packet type 100001
        # one-octet length, header len: 2, body len: 0 to 191
        [0b01100001, 0],
        [0b01100001, 191],
        # two-octet length, header len: 3, body len: 192 to 8383
        [0b01100001, 192, 0],
        [0b01100001, 223, 255],
        # five-octet length, header len: 6, body len: 0 to 4,294,967,295
        [0b01100001, 255, 0, 0, 0, 0],
        [0b01100001, 255, 255, 255, 255, 255],

        ## Old format packet lengths with mock packet type 1001
        # one-octet length, header len: 2, body len: 0 to 255
        [0b00100100, 0],
        [0b00100100, 255],
        # two-octet length, header len: 3, body len: 0 to 65,535
        [0b00100101, 0, 0],
        [0b00100101, 255, 255],
        # four-octet length, header len: 5, body len: 0 to 4,294,967,295
        [0b00100110, 0, 0, 0, 0, 0],
        [0b00100110, 255, 255, 255, 255, 255],
      ]

    # packet_type | header_len | body_len | packet_len
    expected = [
        (33, 2, 0, 2),
        (33, 2, 191, 193),
        (33, 3, 192, 195),
        (33, 3, 8383, 8386),
        (33, 6, 0, 6),
        (33, 6, 4294967295, 4294967301),
        (9, 2, 0, 2),
        (9, 2, 255, 257),
        (9, 3, 0, 3),
        (9, 3, 65535, 65538),
        (9, 5, 0, 5),
        (9, 5, 4294967295, 4294967300),
      ]

    for idx, data in enumerate(data_list):
      result = parse_packet_header(bytearray(data))
      self.assertEqual(result, expected[idx])


    # New Format Packet Lengths with Partial Body Lengths range
    for second_octet in [224, 254]:
      with self.assertRaises(PacketParsingError):
        parse_packet_header(bytearray([0b01100001, second_octet]))

    # Old Format Packet Lengths with indeterminate length (length type 3)
    with self.assertRaises(PacketParsingError):
      parse_packet_header(bytearray([0b00100111]))

    # Get expected type
    parse_packet_header(bytearray([0b01100001, 0]), expected_type=33)

    # Raise with unexpected type
    with self.assertRaises(PacketParsingError):
      parse_packet_header(bytearray([0b01100001, 0]), expected_type=34)


  def test_parse_subpacket_header(self):
    """Test parse_subpacket_header with manually crafted data. """
    # All items until last item encode the length of the subpacket,
    # the last item encodes the mock subpacket type.
    data_list = [
      # length of length 1, subpacket length 0 to 191
      [0, 33], # NOTE: Nonsense 0-length
      [191, 33],
      # # length of length 2, subpacket length 192 to 16,319
      [192, 0, 33],
      [254, 255, 33],
      # # length of length 5, subpacket length 0 to 4,294,967,295
      [255, 0, 0, 0, 0, 33], # NOTE: Nonsense 0-length
      [255, 255, 255, 255, 255, 33],
    ]
    # packet_type | header_len | body_len | packet_len
    expected = [
      (33, 2, -1, 1), # NOTE: Nonsense negative payload
      (33, 2, 190, 192),
      (33, 3, 191, 194),
      (33, 3, 16318, 16321),
      (33, 6, -1, 5), # NOTE: Nonsense negative payload
      (33, 6, 4294967294, 4294967300)
    ]

    for idx, data in enumerate(data_list):
      result = parse_subpacket_header(bytearray(data))
      self.assertEqual(result, expected[idx])


@unittest.skipIf(os.getenv("TEST_SKIP_GPG"), "gpg not found")
class TestCommon(unittest.TestCase):
  """Test common functions of the in_toto.gpg module. """
  @classmethod
  def setUpClass(self):
    # Load test raw public key bundle from rsa keyring, used to construct
    # erroneous gpg data in tests below.
    keyid = "F557D0FF451DEF45372591429EA70BD13D883381"

    gpg_keyring_path = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "gpg_keyrings", "rsa")
    homearg = "--homedir {}".format(gpg_keyring_path)

    cmd = GPG_EXPORT_PUBKEY_COMMAND.format(keyid=keyid, homearg=homearg)
    proc = process.run(cmd, stdout=process.PIPE, stderr=process.PIPE)

    self.raw_key_data = proc.stdout
    self.raw_key_bundle = parse_pubkey_bundle(self.raw_key_data)


  def test_parse_pubkey_payload_errors(self):
    """ Test parse_pubkey_payload errors with manually crafted data. """
    # passed data | expected error | expected error message
    test_data = [
      (None, ValueError, "empty pubkey"),
      (bytearray([0x03]), PacketVersionNotSupportedError,
          "packet version '3' not supported"),
      (bytearray([0x04, 0, 0, 0, 0, 255]), SignatureAlgorithmNotSupportedError,
          "Signature algorithm '255' not supported")
    ]

    for data, error, error_str in test_data:
      with self.assertRaises(error) as ctx:
        parse_pubkey_payload(data)
      self.assertTrue(error_str in str(ctx.exception))


  def test_parse_pubkey_bundle_errors(self):
    """Test parse_pubkey_bundle errors with manually crafted data partially
    based on a real gpg key data (see self.raw_key_bundle) . """
    # Extract sample (legitimate) user ID packet and pass as first packet to
    # raise first packet must be primary key error
    user_id_packet = list(self.raw_key_bundle[PACKET_TYPE_USER_ID].keys())[0]
    # Extract sample (legitimate) primary key packet and pass as first two
    # packets to raise unexpected second primary key error
    primary_key_packet = self.raw_key_bundle[PACKET_TYPE_PRIMARY_KEY]["packet"]
    # Create incomplete packet to re-raise header parsing IndexError as
    # PacketParsingError
    incomplete_packet = bytearray([0b01111111])

    # passed data | expected error message
    test_data = [
      (None, "empty gpg data"),
      (user_id_packet, "must be a primary key"),
      (primary_key_packet + primary_key_packet, "Unexpected primary key"),
      (incomplete_packet, "index out of range")
    ]
    for data, error_str in test_data:
      with self.assertRaises(PacketParsingError) as ctx:
        parse_pubkey_bundle(data)
      self.assertTrue(error_str in str(ctx.exception))

    # Create empty packet of unsupported type 66 (bit 0-5) and length 0 and
    # pass as second packet to provoke skipping of unsupported packet
    unsupported_packet = bytearray([0b01111111, 0])
    with patch("in_toto.gpg.common.log") as mock_log:
      parse_pubkey_bundle(primary_key_packet + unsupported_packet)
      self.assertTrue("Ignoring gpg key packet '63'" in
          mock_log.info.call_args[0][0])


  def test_parse_pubkey_bundle(self):
    """Assert presence of packets expected returned from `parse_pubkey_bundle`
    for specific test key). See
    ```
    gpg --homedir tests/gpg_keyrings/rsa/ --export 9EA70BD13D883381 | \
        gpg --list-packets
    ```
    """
    # Expect parsed primary key matching PUBKEY_SCHEMA
    self.assertTrue(PUBKEY_SCHEMA.matches(
         self.raw_key_bundle[PACKET_TYPE_PRIMARY_KEY]["key"]))

    # Parse corresponding raw packet for comparison
    _, header_len, _, _ = parse_packet_header(
        self.raw_key_bundle[PACKET_TYPE_PRIMARY_KEY]["packet"])
    parsed_raw_packet = parse_pubkey_payload(bytearray(
          self.raw_key_bundle[PACKET_TYPE_PRIMARY_KEY]["packet"][header_len:]))

    # And compare
    self.assertDictEqual(
        self.raw_key_bundle[PACKET_TYPE_PRIMARY_KEY]["key"],
        parsed_raw_packet)

    # Expect one primary key signature (revocation signature)
    self.assertEqual(
        len(self.raw_key_bundle[PACKET_TYPE_PRIMARY_KEY]["signatures"]), 1)

    # Expect one User ID packet, one User Attribute packet and one Subkey,
    # each with correct data
    for _type in [PACKET_TYPE_USER_ID, PACKET_TYPE_USER_ATTR,
        PACKET_TYPE_SUB_KEY]:
      # Of each type there is only one packet
      self.assertTrue(len(self.raw_key_bundle[_type]) == 1)
      # The raw packet is stored as key in the per-packet type collection
      raw_packet = next(iter(self.raw_key_bundle[_type]))
      # Its values are the raw packets header and body length
      self.assertEqual(len(raw_packet),
          self.raw_key_bundle[_type][raw_packet]["header_len"] +
          self.raw_key_bundle[_type][raw_packet]["body_len"])
      # and one self-signature
      self.assertEqual(
          len(self.raw_key_bundle[_type][raw_packet]["signatures"]), 1)


  def test_get_pubkey_bundle_errors(self):
    """Pass wrong keyid with valid gpg data to trigger KeyNotFoundError. """
    not_associated_keyid = "8465A1E2E0FB2B40ADB2478E18FB3F537E0C8A17"
    with self.assertRaises(KeyNotFoundError):
      get_pubkey_bundle(self.raw_key_data, not_associated_keyid)


@unittest.skipIf(os.getenv("TEST_SKIP_GPG"), "gpg not found")
class TestGPGRSA(unittest.TestCase):
  """Test signature creation, verification and key export from the gpg
  module"""
  default_keyid = "8465A1E2E0FB2B40ADB2478E18FB3F537E0C8A17"
  signing_subkey_keyid = "C5A0ABE6EC19D0D65F85E2C39BE9DF5131D924E9"
  encryption_subkey_keyid = "6A112FD3390B2E53AFC2E57F8FC8E12099AECEEA"
  unsupported_subkey_keyid = "611A9B648E16F54E8A7FAD5DA51E8CDF3B06524F"

  @classmethod
  def setUpClass(self):
    # Create directory to run the tests without having everything blow up
    self.working_dir = os.getcwd()

    # Find demo files
    gpg_keyring_path = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "gpg_keyrings", "rsa")

    self.test_dir = os.path.realpath(tempfile.mkdtemp())
    self.gnupg_home = os.path.join(self.test_dir, "rsa")
    shutil.copytree(gpg_keyring_path, self.gnupg_home)
    os.chdir(self.test_dir)


  @classmethod
  def tearDownClass(self):
    """Change back to initial working dir and remove temp test directory. """
    os.chdir(self.working_dir)
    shutil.rmtree(self.test_dir)


  def test_gpg_export_pubkey(self):
    """ export a public key and make sure the parameters are the right ones:

      since there's very little we can do to check rsa key parameters are right
      we pre-exported the public key to an ssh key, which we can load with
      cryptography for the sake of comparison """

    # export our gpg key, using our functions
    key_data = gpg_export_pubkey(self.default_keyid, homedir=self.gnupg_home)
    our_exported_key = rsa_create_pubkey(key_data)

    # load the equivalent ssh key, and make sure that we get the same RSA key
    # parameters
    ssh_key_basename = "{}.ssh".format(self.default_keyid)
    ssh_key_path = os.path.join(self.gnupg_home, ssh_key_basename)
    with open(ssh_key_path, "rb") as fp:
      keydata = fp.read()

    ssh_key = serialization.load_ssh_public_key(keydata,
        backends.default_backend())

    self.assertEquals(ssh_key.public_numbers().n,
        our_exported_key.public_numbers().n)
    self.assertEquals(ssh_key.public_numbers().e,
        our_exported_key.public_numbers().e)

    subkey_keyids = list(key_data["subkeys"].keys())
    # We export the whole master key bundle which must contain the subkeys
    self.assertTrue(self.signing_subkey_keyid.lower() in subkey_keyids)
    # Currently we do not exclude encryption subkeys
    self.assertTrue(self.encryption_subkey_keyid.lower() in subkey_keyids)
    # However we do exclude subkeys, whose algorithm we do not support
    self.assertFalse(self.unsupported_subkey_keyid.lower() in subkey_keyids)

    # When passing the subkey keyid we also export the whole keybundle
    key_data2 = gpg_export_pubkey(self.signing_subkey_keyid,
        homedir=self.gnupg_home)
    self.assertDictEqual(key_data, key_data2)


  def test_gpg_sign_and_verify_object_with_default_key(self):
    """Create a signature using the default key on the keyring """

    test_data = b'test_data'
    wrong_data = b'something malicious'

    signature = gpg_sign_object(test_data, homedir=self.gnupg_home)
    key_data = gpg_export_pubkey(self.default_keyid, homedir=self.gnupg_home)

    self.assertTrue(gpg_verify_signature(signature, key_data, test_data))
    self.assertFalse(gpg_verify_signature(signature, key_data, wrong_data))



  def test_gpg_sign_and_verify_object(self):
    """Create a signature using a specific key on the keyring """

    test_data = b'test_data'
    wrong_data = b'something malicious'

    signature = gpg_sign_object(test_data, keyid=self.default_keyid,
        homedir=self.gnupg_home)
    key_data = gpg_export_pubkey(self.default_keyid, homedir=self.gnupg_home)
    self.assertTrue(gpg_verify_signature(signature, key_data, test_data))
    self.assertFalse(gpg_verify_signature(signature, key_data, wrong_data))


  def test_gpg_sign_and_verify_object_default_keyring(self):
    """Sign/verify using keyring from envvar. """

    test_data = b'test_data'

    gnupg_home_backup = os.environ.get("GNUPGHOME")
    os.environ["GNUPGHOME"] = self.gnupg_home

    signature = gpg_sign_object(test_data, keyid=self.default_keyid)
    key_data = gpg_export_pubkey(self.default_keyid)
    self.assertTrue(gpg_verify_signature(signature, key_data, test_data))

    # Reset GNUPGHOME
    if gnupg_home_backup:
      os.environ["GNUPGHOME"] = gnupg_home_backup
    else:
      del os.environ["GNUPGHOME"]


@unittest.skipIf(os.getenv("TEST_SKIP_GPG"), "gpg not found")
class TestGPGDSA(unittest.TestCase):
  """ Test signature creation, verification and key export from the gpg
  module """

  default_keyid = "C242A830DAAF1C2BEF604A9EF033A3A3E267B3B1"

  @classmethod
  def setUpClass(self):
    # Create directory to run the tests without having everything blow up
    self.working_dir = os.getcwd()
    self.test_dir = os.path.realpath(tempfile.mkdtemp())
    self.gnupg_home = os.path.join(self.test_dir, "dsa")

    # Find keyrings
    keyrings = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "gpg_keyrings", "dsa")

    shutil.copytree(keyrings, self.gnupg_home)
    os.chdir(self.test_dir)

  @classmethod
  def tearDownClass(self):
    """Change back to initial working dir and remove temp test directory. """
    os.chdir(self.working_dir)
    shutil.rmtree(self.test_dir)

  def test_gpg_export_pubkey(self):
    """ export a public key and make sure the parameters are the right ones:

      since there's very little we can do to check rsa key parameters are right
      we pre-exported the public key to an ssh key, which we can load with
      cryptography for the sake of comparison """

    # export our gpg key, using our functions
    key_data = gpg_export_pubkey(self.default_keyid, homedir=self.gnupg_home)
    our_exported_key = dsa_create_pubkey(key_data)

    # load the equivalent ssh key, and make sure that we get the same RSA key
    # parameters
    ssh_key_basename = "{}.ssh".format(self.default_keyid)
    ssh_key_path = os.path.join(self.gnupg_home, ssh_key_basename)
    with open(ssh_key_path, "rb") as fp:
      keydata = fp.read()

    ssh_key = serialization.load_ssh_public_key(keydata,
        backends.default_backend())

    self.assertEquals(ssh_key.public_numbers().y,
        our_exported_key.public_numbers().y)
    self.assertEquals(ssh_key.public_numbers().parameter_numbers.g,
        our_exported_key.public_numbers().parameter_numbers.g)
    self.assertEquals(ssh_key.public_numbers().parameter_numbers.q,
        our_exported_key.public_numbers().parameter_numbers.q)
    self.assertEquals(ssh_key.public_numbers().parameter_numbers.p,
        our_exported_key.public_numbers().parameter_numbers.p)

  def test_gpg_sign_and_verify_object_with_default_key(self):
    """Create a signature using the default key on the keyring """

    test_data = b'test_data'
    wrong_data = b'something malicious'

    signature = gpg_sign_object(test_data, homedir=self.gnupg_home)
    key_data = gpg_export_pubkey(self.default_keyid, homedir=self.gnupg_home)

    self.assertTrue(gpg_verify_signature(signature, key_data, test_data))
    self.assertFalse(gpg_verify_signature(signature, key_data, wrong_data))


  def test_gpg_sign_and_verify_object(self):
    """Create a signature using a specific key on the keyring """

    test_data = b'test_data'
    wrong_data = b'something malicious'

    signature = gpg_sign_object(test_data, keyid=self.default_keyid,
        homedir=self.gnupg_home)
    key_data = gpg_export_pubkey(self.default_keyid, homedir=self.gnupg_home)

    self.assertTrue(gpg_verify_signature(signature, key_data, test_data))
    self.assertFalse(gpg_verify_signature(signature, key_data, wrong_data))


if __name__ == "__main__":
  unittest.main()
