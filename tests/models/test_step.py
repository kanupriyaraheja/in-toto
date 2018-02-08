#!/usr/bin/env python
"""
<Program Name>
  test_step.py

<Author>
  Santiago Torres-Arias <santiago@nyu.edu>

<Started>
  Nov 18, 2016

<Copyright>
  See LICENSE for licensing information.

<Purpose>
  Test step class functions.

"""

import unittest
import datetime
from in_toto.models.layout import Step
import securesystemslib.keys
import securesystemslib.exceptions

class TestStepValidator(unittest.TestCase):
  """Test verifylib.verify_delete_rule(rule, artifact_queue) """

  def setUp(self):
    """Populate a base layout that we can use."""
    self.step = Step(name="this-step")

  def test_wrong_type(self):
    """Test the type field within Validate()."""

    self.step._type = "wrong"
    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step._validate_type()

    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step.validate()

    self.step._type = "step"
    self.step._validate_type()

  def test_wrong_threshold(self):
    """Test that the threshold value is correctly checked."""

    # no, python is not *this* smart
    self.step.threshold = "Ten"
    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step._validate_threshold()

    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step.validate()

    self.step.threshold = 10
    self.step._validate_threshold()
    self.step.validate()

  def test_wrong_expected_materials(self):
    """Test that the material rule validators catch malformed ones."""

    self.step.expected_materials = [["NONFOO"]]
    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step._validate_expected_materials()

    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step.validate()

    self.step.expected_materials = "PFF"
    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step._validate_expected_materials()

    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step.validate()

    # for more thorough tests, check the test_rulelib.py module
    self.step.expected_materials = [["CREATE", "foo"]]
    self.step._validate_expected_materials()
    self.step.validate()

  def test_wrong_expected_products(self):
    """Test that the product rule validators catch malformed ones."""

    self.step.expected_products = [["NONFOO"]]
    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step._validate_expected_products()

    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step.validate()

    self.step.expected_products = "PFF"
    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step._validate_expected_products()

    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step.validate()

    # for more thorough tests, check the test_rulelib.py module
    self.step.expected_products = [["CREATE", "foo"]]
    self.step._validate_expected_products()
    self.step.validate()

  def test_wrong_pubkeys(self):
    # FIXME: generating keys for each test are expensive processes, maybe we
    # should have an asset/fixture folder/loader?

    rsa_key_one = securesystemslib.keys.generate_rsa_key()
    rsa_key_two = securesystemslib.keys.generate_rsa_key()

    self.step.pubkeys = ['bad-keyid']

    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step._validate_pubkeys()

    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step.validate()

    self.step.pubkeys = [rsa_key_one['keyid'], rsa_key_two['keyid']]
    self.step._validate_pubkeys()
    self.step.validate()

  def test_wrong_expected_command(self):
    """Test that the expected command validator catches malformed ones."""

    self.step.expected_command = -1
    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step._validate_expected_command()

    with self.assertRaises(securesystemslib.exceptions.FormatError):
      self.step.validate()

    self.step.expected_command = ["somecommand"]
    self.step._validate_expected_command()
    self.step.validate()

if __name__ == '__main__':

  unittest.main()