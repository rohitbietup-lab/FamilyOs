"""Synthetic PDF regressions; no private documents or live scanner required."""
import io
from unittest.mock import patch

from django.test import SimpleTestCase
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from vault import storage


class PdfValidationTests(SimpleTestCase):
    def pdf(self, page_entries):
        writer = PdfWriter()
        page = writer.add_blank_page(width=100, height=100)
        page.update(page_entries)
        stream = io.BytesIO()
        writer.write(stream)
        return stream.getvalue()

    @patch('vault.storage.scan')
    def test_subset_font_name_is_accepted(self, scan):
        font = DictionaryObject({
            NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'),
            NameObject('/BaseFont'): NameObject('/AAAAAA+LiberationSans'),
            NameObject('/FontDescriptor'): DictionaryObject({
                NameObject('/Type'): NameObject('/FontDescriptor'),
                NameObject('/FontName'): NameObject('/AAAAAA+LiberationSans'),
            }),
        })
        data = self.pdf({NameObject('/Resources'): DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font}),
        })})
        self.assertIn(b'/AAAAAA+LiberationSans', data)
        self.assertEqual(storage.validate(data, 'synthetic.pdf'), 'application/pdf')
        scan.assert_called_once_with(data)

    @patch('vault.storage.scan')
    def test_real_additional_action_is_rejected(self, scan):
        # A URI action isolates /AA detection from the other forbidden names.
        action = DictionaryObject({
            NameObject('/S'): NameObject('/URI'),
            NameObject('/URI'): TextStringObject('https://example.test/'),
        })
        data = self.pdf({NameObject('/AA'): DictionaryObject({NameObject('/O'): action})})
        self.assertIn('/AA', PdfReader(io.BytesIO(data), strict=True).pages[0])
        with self.assertRaises(storage.RejectedFile):
            storage.validate(data, 'synthetic-action.pdf')
        scan.assert_called_once_with(data)

    @patch('vault.storage.scan')
    def test_all_active_names_are_rejected(self, scan):
        for name in ('/JavaScript', '/JS', '/Launch', '/EmbeddedFile', '/OpenAction', '/AA', '/RichMedia'):
            with self.subTest(name=name):
                data = self.pdf({NameObject(name): DictionaryObject()})
                with self.assertRaises(storage.RejectedFile):
                    storage.validate(data, 'synthetic-active.pdf')

    @patch('vault.storage.scan')
    def test_escaped_active_names_are_rejected_in_valid_pdfs(self, scan):
        for name in ('/JavaScript', '/JS', '/Launch', '/EmbeddedFile', '/OpenAction', '/AA', '/RichMedia'):
            with self.subTest(name=name):
                escaped = b'/' + b''.join(b'#%02x' % value for value in name[1:].encode('ascii'))
                placeholder = '/' + 'X' * (len(escaped) - 1)
                data = self.pdf({NameObject(placeholder): DictionaryObject()})
                # Equal-length replacement preserves the writer's xref offsets.
                data = data.replace(placeholder.encode('ascii'), escaped)
                self.assertIn(name, PdfReader(io.BytesIO(data), strict=True).pages[0])
                with self.assertRaises(storage.RejectedFile):
                    storage.validate(data, 'synthetic-escaped.pdf')

    def test_pdf_name_boundaries_and_escapes(self):
        for name in (b'/JavaScript', b'/JS', b'/Launch', b'/EmbeddedFile', b'/OpenAction', b'/AA', b'/RichMedia'):
            for ending in (b'', b'\x00', b'\t', b'\n', b'\f', b'\r', b' ', b'(', b')', b'<', b'>', b'[', b']', b'{', b'}', b'/', b'%'):
                with self.subTest(name=name, ending=ending):
                    self.assertTrue(storage._has_active_pdf_name(name + ending))
            escaped = b'/' + b''.join(b'#%02x' % value for value in name[1:])
            self.assertTrue(storage._has_active_pdf_name(escaped + b'<<>>'))
            for suffix in (b'AAAA+LiberationSans', b'+Font', b'-Font', b'_Font', b'#20Font', b'#2fFont'):
                with self.subTest(name=name, suffix=suffix):
                    self.assertFalse(storage._has_active_pdf_name(name + suffix))
