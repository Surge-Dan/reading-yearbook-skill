import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'reading-yearbook-skill' / 'scripts'))
from build_reading_html import adapt_data, build_html, date_value, merge_annual, merge_materials, number
from test_report_reader import bundle


def fixture():
    return {'year': 2026, 'as_of': '2026-10-01', 'source_mode': 'sample', 'distillations':[bundle(sample=True)],
            'summary': {'book_count': 3, 'finished_count': 1, 'total_read_seconds': 162213,
                        'read_days': 172, 'note_count': 4,
                        'monthly_read_seconds': [24505,14639,None,25239,23324,0,7347,21932,19503,2,0,0]},
            'books': [
                {'book_id': 'one', 'title': '一本关于城市与生活的书', 'author': '作者甲', 'category': '社会', 'progress': 100,
                 'highlights': [{'text': '原文摘录，保留准确的句子。', 'source_id': 'h1', 'created_at': '2026-05-04'}],
                 'thoughts': [{'text': '这是我的个人笔记。', 'source_id': 't1', 'created_at': '2026-05-05'}]},
                {'book_id': 'two', 'title': 'YES！产品经理——一个非常长的书名，用来检查中文断行与分享图片的排版',
                 'author': '作者乙', 'category': '方法', 'progress': 50,
                 'highlights': [{'text': '判断可以改变，记录要准确。', 'source_id': 'h2', 'created_at': '2026-07-30'}]},
                {'book_id': 'three', 'title': '未记录状态的书', 'author': '作者丙', 'category': '方法', 'progress': None,
                 'highlights': [{'text': '日期未记录的摘录。', 'source_id': 'h3'}]}
            ]}


class ReadingHtmlTests(unittest.TestCase):
    def test_formal_yearbook_requires_every_cover_and_preserves_previous_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'index.html';path.write_text('previous valid version','utf-8')
            with self.assertRaisesRegex(ValueError,'缺少真实封面'):
                build_html(adapt_data(fixture()),path,require_all_covers=True)
            self.assertEqual(path.read_text('utf-8'),'previous valid version')

    def test_complete_materials_include_historical_notes_without_changing_year_totals(self):
        data=adapt_data(fixture())
        material={'year':2026,'books':[{'book_id':'one','progress':84,'notes_scope':'all_time',
                   'collection':{'progress':'complete','highlights':'complete','thoughts':'complete'},
                   'highlights':[{'text':'old personal highlight','created_at':'2025-10-01','source_id':'old'}],
                   'thoughts':[]}]}
        merge_materials(data,material)
        self.assertEqual(data['books'][0]['progress'],84)
        self.assertEqual(data['books'][0]['highlights'][0]['created_at'],'2025-10-01')
        self.assertEqual(data['summary']['notes'],4)
        self.assertEqual(data['books'][0]['note_coverage']['thoughts'],'complete')

    def test_failed_material_collection_preserves_existing_notes(self):
        data=adapt_data(fixture())
        merge_materials(data,{'year':2026,'books':[{'book_id':'one','collection':{'highlights':'failed'},'highlights':[]}]})
        self.assertEqual(len(data['books'][0]['highlights']),1)
        self.assertEqual(data['books'][0]['note_coverage']['highlights'],'unverified')

    def test_material_year_mismatch_and_unrelated_books(self):
        data=adapt_data(fixture())
        with self.assertRaisesRegex(ValueError,'年份'):
            merge_materials(data,{'year':2025,'books':[]})
        merge_materials(data,{'year':2026,'books':[{'book_id':'unrelated'}]})
        self.assertEqual(len(data['books']),3)

    def test_official_annual_totals_refresh_without_overwriting_current_progress(self):
        data=adapt_data(fixture())
        merge_annual(data,{'year':2026,'as_of':'2026-10-05','annual':{'readStat':[{'stat':'读过','counts':'3本'}, {'stat':'读完','counts':'2本'}, {'stat':'笔记','counts':'9条'}], 'readDays':174, 'totalReadTime':163315}})
        self.assertEqual(data['summary']['finished'],2)
        self.assertEqual(data['summary']['notes'],9)
        self.assertEqual(data['summary']['seconds'],163315)
        self.assertEqual(sum(b['status']=='finished' for b in data['books']),1)

    def test_art_resources_are_embedded_once_outside_reading_data(self):
        import base64
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'index.html';build_html(adapt_data(fixture()),path)
            text=path.read_text('utf-8')
            encoded=base64.b64encode((ROOT/'reading-yearbook-skill/assets/yearbook-art/hero-book.png').read_bytes()).decode('ascii')
            self.assertEqual(text.count(encoded),1)
            self.assertIn('id="reading-art"',text)
            data=json.loads(text.split('<script id="reading-data" type="application/json">')[1].split('</script>')[0])
            self.assertNotIn('art',data)

    def test_unknown_art_asset_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'未知艺术素材'):
                build_html(adapt_data(fixture()),Path(tmp)/'index.html',art_assets={'unknown':'missing.png'})

    def test_unknown_is_not_zero_or_reading(self):
        b = adapt_data(fixture())['books'][2]
        self.assertIsNone(b['progress'])
        self.assertEqual(b['status'], 'unknown')

    def test_missing_zero_and_future_are_distinct(self):
        monthly = adapt_data(fixture())['summary']['monthly']
        self.assertIsNone(monthly[2])
        self.assertEqual(monthly[5], 0)
        self.assertIsNone(monthly[10])

    def test_partial_month_excluded_from_complete_month_chart(self):
        data = adapt_data(fixture())
        self.assertEqual(data['summary']['complete_months'], 9)
        self.assertEqual(data['summary']['monthly'][9], 2)

    def test_unobserved_normalized_zero_is_missing(self):
        raw = fixture()
        raw['summary']['monthly_observed'] = [False] * 12
        self.assertTrue(all(v is None for v in adapt_data(raw)['summary']['monthly']))

    def test_year_filter_and_duplicate_source_ids(self):
        raw = fixture()
        raw['books'][0]['highlights'] += [{'text':'old', 'created_at':'2025-01-01'}, raw['books'][0]['highlights'][0]]
        self.assertEqual(len(adapt_data(raw)['books'][0]['highlights']), 1)

    def test_no_initial_or_completion_dates_inferred_from_notes(self):
        b = adapt_data(fixture())['books'][0]
        self.assertIsNone(b['start_date'])
        self.assertIsNone(b['finish_date'])

    def test_invalid_numbers_do_not_enter_json(self):
        for n in [float('nan'), float('inf'), -1, True, {}, 'bad']:
            self.assertIsNone(number(n))
        raw = fixture()
        raw['books'][0]['progress'] = 101
        self.assertIsNone(adapt_data(raw)['books'][0]['progress'])

    def test_invalid_dates_and_timezone(self):
        self.assertIsNone(date_value('2026-02-31'))
        self.assertEqual(date_value(1767196800), '2026-01-01')

    def test_coverage_is_loaded_not_annual(self):
        raw = fixture()
        raw['summary']['book_count'] = 15
        data = adapt_data(raw)
        self.assertEqual(data['coverage']['loaded_books'], 3)
        self.assertFalse(data['coverage']['complete'])

    def test_duplicate_books_do_not_change_distribution(self):
        raw=fixture();raw['books'].append(raw['books'][0])
        self.assertEqual(len(adapt_data(raw)['books']), 3)

    def test_legacy_review_is_ignored_in_yearbook_data(self):
        raw=fixture();raw['books'][0]['full_text_review']={'status':'verified','body':'private generated review'}
        data=adapt_data(raw)
        self.assertNotIn('review',data['books'][0])
        self.assertNotIn('private generated review',json.dumps(data))

    def test_legacy_search_and_review_are_removed_at_build_boundary(self):
        data=adapt_data(fixture());data['books'][0].update(review={'body':'obsolete review'},full_text_search={'reason':'obsolete source'})
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'index.html';build_html(data,target)
            text=target.read_text('utf-8')
            self.assertNotIn('obsolete review',text);self.assertNotIn('obsolete source',text)

    def test_invalid_monthly_shape_rejected(self):
        raw=fixture();raw['summary']['monthly_read_seconds']={'1':20}
        with self.assertRaisesRegex(ValueError,'列表'):
            adapt_data(raw)

    def test_category_hierarchy_maps_to_one_primary_category(self):
        raw=fixture();raw['books'][0]['category']='社会-城市'
        b=adapt_data(raw)['books'][0]
        self.assertEqual(b['category'],'社会')
        self.assertEqual(b['source_category'],'社会-城市')

    def test_only_positive_year_activity_merges_not_entire_shelf(self):
        snap={'year':2026,'shelf':{'books':[{'bookId':'unread','title':'Unread'}]},'annual':{'readLongest':[]},
              'non_ranked_progress':[{'book_id':'unread','is_started':0,'last_read':'2026-09-01'},
                                     {'book_id':'old','is_started':1,'last_read':'2025-09-01'}]}
        data=merge_annual(adapt_data(fixture()),snap)
        self.assertEqual(len(data['books']), 3)

    def test_snapshot_wrong_year_cannot_pollute_annual_books(self):
        with self.assertRaisesRegex(ValueError,'年份'):
            merge_annual(adapt_data(fixture()),{'year':2025,'annual':{}})

    def test_private_payload_fields_are_whitelisted(self):
        raw=fixture();raw['WEREAD_API_KEY']='private-key';raw['books'][0]['cookie']='private-cookie'
        s=json.dumps(adapt_data(raw))
        self.assertNotIn('private-key',s);self.assertNotIn('private-cookie',s)

    def test_embedded_script_is_not_executable_and_delimiters_are_literal(self):
        raw=fixture();raw['books'][0]['title']='</script><script>window.PWNED=1</script>__APP__'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'index.html';build_html(adapt_data(raw),path)
            text=path.read_text('utf-8')
            self.assertNotIn('</script><script>window.PWNED=1',text)
            self.assertIn('\\u003c/script>',text)
            self.assertIn('__APP__',text)

    def test_key_like_text_blocks_delivery(self):
        raw=fixture();raw['books'][0]['title']='wrk-abcdefgh12345678'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, '密钥'):
                build_html(adapt_data(raw),Path(tmp)/'index.html')


if __name__=='__main__':
    unittest.main()
