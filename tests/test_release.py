import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from app.config import load_private_environment
from app.graph_data import excel_records
from scripts.check_secrets import findings
from scripts.prepare_demo_data import prepare
from scripts.rebuild_graph import GraphBuilder

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_private_environment_precedence(self):
        with TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            root=Path(d); project=root/'project'; project.mkdir()
            private=root/'settings'/'VRS'; private.mkdir(parents=True)
            (private/'private.env').write_text('TEST_VRS_VALUE=private\nTEST_VRS_FALLBACK=private\n')
            (project/'.env').write_text('TEST_VRS_VALUE=project\n')
            explicit=root/'explicit.env'; explicit.write_text('TEST_VRS_VALUE=explicit\n')
            os.environ.update(APPDATA=str(root/'settings'),VRS_ENV_FILE=str(explicit))
            load_private_environment(project)
            self.assertEqual(os.environ['TEST_VRS_VALUE'],'explicit')
            self.assertEqual(os.environ['TEST_VRS_FALLBACK'],'private')
            os.environ['TEST_VRS_VALUE']='process'
            load_private_environment(project)
            self.assertEqual(os.environ['TEST_VRS_VALUE'],'process')

    def test_public_configuration_has_no_credentials(self):
        for path in ['.env.example','setting.yaml']:
            self.assertEqual(findings((ROOT/path).read_bytes()),[],path)

    def test_templates_match_the_schema_and_preserve_text_codes(self):
        schema=json.loads((ROOT/'data_templates/schema.json').read_text(encoding='utf-8'))
        self.assertEqual(len(schema['workbooks']),14)
        for spec in schema['workbooks']:
            with self.subTest(file=spec['filename']):
                rows=list(excel_records(ROOT/'data_templates'/spec['filename']))
                self.assertEqual(len(rows),len(spec['rows']))
                self.assertEqual(list(rows[0][2]),[c['name'] for c in spec['columns']])
                for (_,_,row),expected in zip(rows,spec['rows']):
                    self.assertEqual(list(row.values()),[None if value=='' else value for value in expected])
                for column in spec['columns']:
                    if '代码' in column['name']:
                        self.assertTrue(all(isinstance(r[2][column['name']],str) for r in rows))

    def test_template_preflight_never_connects_to_database(self):
        client=Mock()
        self.assertEqual(len(GraphBuilder(client,ROOT/'data_templates').validate_sources()),14)
        client.run.assert_not_called()
        client.run_rows.assert_not_called()

    def test_demo_preparation_refuses_existing_files(self):
        with TemporaryDirectory() as d:
            target=Path(d)/'demo'
            self.assertEqual(prepare(target),14)
            first=next(target.glob('*.xlsx')); before=first.read_bytes()
            with self.assertRaisesRegex(ValueError,'拒绝覆盖'):
                prepare(target)
            self.assertEqual(first.read_bytes(),before)

    def test_rank_header_variants_keep_board_location_and_score(self):
        builder=GraphBuilder(Mock(),ROOT/'data_templates')
        builder.file_ids={p.name:p.name for p in (ROOT/'data_templates').glob('*.xlsx')}
        captured=[]
        builder.emit=lambda kind,query,row: captured.append((kind,row))
        builder.rankings()
        rankings=[r for kind,r in captured if kind=='rankings']
        self.assertEqual(len(rankings),7)
        self.assertTrue(all(r['props']['score']==80 for r in rankings))
        self.assertEqual({r['props']['list_type'] for r in rankings},{'QS','U.S.News','校友会','泰晤士','软科'})
        self.assertTrue(all(r['props']['province']=='浙江' for kind,r in captured if kind=='institution_updates'))

    def test_secret_scanner_reports_locations_without_values(self):
        raw=('API_KEY=sk-'+('a'*32)+'\nNEO4J_PASSWORD=not-a-real-password\n').encode()
        result=findings(raw)
        self.assertEqual({kind for kind,_ in result},{'provider_token','password_assignment'})
        self.assertNotIn('not-a-real-password',repr(result))


if __name__=='__main__':
    unittest.main()
