"""The browser fixture must be reproducible from committed, controlled evidence."""
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reading-yearbook-skill/scripts'))
from distillation_result import validate_bundle


class BrowserFixtureTests(unittest.TestCase):
    def test_committed_builder_produces_two_public_sample_packages(self):
        path=ROOT/'tests/build_report_reader_fixture.py'
        self.assertTrue(path.is_file(),'missing committed browser fixture builder')
        spec=importlib.util.spec_from_file_location('report_fixture',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'index.html';module.build_fixture(output)
            page=output.read_text('utf-8')
            data=json.loads(re.search(r'<script id="reading-data" type="application/json">(.*?)</script>',page,re.S).group(1))
            self.assertEqual(data['source_mode'],'sample')
            self.assertEqual(len(data['distillations']),2)
            self.assertEqual({b['input_mode'] for b in data['distillations']},{'upload','title'})
            for bundle in data['distillations']:
                self.assertEqual(validate_bundle(bundle),bundle)
                self.assertEqual(bundle['source_mode'],'sample')
                self.assertNotIn(str(Path(tmp)),json.dumps(bundle))
            self.assertEqual(data['summary']['read'],0)
            self.assertEqual(data['books'],[])


if __name__=='__main__':unittest.main()
