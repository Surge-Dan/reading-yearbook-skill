import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reading-yearbook-skill/scripts'))
from generate_reading_html import annual_data, collect_snapshot, deliver, main, cache_directory


def snapshot(count=1):
    return {'year':2026,'as_of':'2026-10-05','shelf':{'books':[]},'annual':{
        'readStat':[{'stat':'读过','counts':f'{count}本'},{'stat':'笔记','counts':'0条'}],
        'readLongest':([] if count==0 else [{'book':{'bookId':'one','title':'示例书','author':'甲'},'readTime':120}])}}


class DeliveryTests(unittest.TestCase):
    def test_cache_isolated_between_authorizations_without_literal_credentials(self):
        one=cache_directory('private/cache','first-secret-key',2026)
        two=cache_directory('private/cache','second-secret-key',2026)
        self.assertNotEqual(one,two)
        self.assertNotIn('first-secret-key',str(one))

    def test_zero_books_and_zero_notes_deliver_a_complete_yearbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=deliver(snapshot(0),{'year':2026,'books':[]},{},Path(tmp)/'index.html')
            self.assertEqual(result['status'],'complete')
            self.assertTrue(Path(result['output']).exists())

    def test_missing_cover_blocks_delivery_preserving_final_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'index.html';target.write_text('previous valid file','utf-8')
            result=deliver(snapshot(),{'year':2026,'books':[]},{},target)
            self.assertEqual(result['status'],'blocked')
            self.assertEqual(result['missing_covers'],1)
            self.assertEqual(target.read_text('utf-8'),'previous valid file')
            self.assertIsNone(result['output'])
            self.assertFalse(target.with_name('index-draft.html').exists())

    def test_successful_empty_notes_do_not_block_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cover=root/'cover.png'
            cover.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAADCAIAAAA2iEnWAAAAFElEQVR4nGP8/ukpAwMDEwMYQCkANbAC1LhAEWwAAAAASUVORK5CYII='))
            materials={'year':2026,'books':[{'book_id':'one','notes_scope':'all_time','collection':{'highlights':'complete','thoughts':'complete'},'highlights':[],'thoughts':[],'errors':[]}]}
            result=deliver(snapshot(),materials,{'one':str(cover)},root/'index.html')
            self.assertEqual(result['status'],'complete')

    def test_incomplete_year_coverage_is_never_claimed_complete(self):
        data=annual_data(snapshot(2))
        self.assertFalse(data['coverage']['complete'])
        self.assertEqual(len(data['books']),1)

    def test_missing_annual_count_does_not_become_a_verified_zero(self):
        source=snapshot(0);source['annual']['readStat']=[{'stat':'笔记','counts':'0条'}]
        data=annual_data(source)
        self.assertIsNone(data['summary']['read'])
        self.assertFalse(data['coverage']['complete'])

    def test_partial_refresh_preserves_notes_from_same_account_year_cache(self):
        previous=annual_data(snapshot());previous['books'][0]['highlights']=[{'text':'上次取得的真实句子','source_id':'old','created_at':'2026-09-01'}]
        failed={'year':2026,'books':[{'book_id':'one','notes_scope':'all_time','collection':{'highlights':'failed','thoughts':'complete'},'thoughts':[],'errors':[{'scope':'highlights'}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state.json'
            deliver(snapshot(),failed,{},root/'index.html',previous,state)
            saved=json.loads(state.read_text('utf-8'))
            self.assertEqual(saved['books'][0]['highlights'][0]['text'],'上次取得的真实句子')
            self.assertEqual(saved['books'][0]['note_coverage']['highlights'],'unverified')
            self.assertNotIn('cover',saved['books'][0])

    def test_complete_annual_list_skips_extra_discovery_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('generate_reading_html.call',side_effect=[{'books':[]},snapshot()['annual']]) as request:
                collect_snapshot(2026,'secret',tmp)
                self.assertEqual(request.call_count,2)
            self.assertNotIn('secret',(Path(tmp)/'annual-snapshot.json').read_text('utf-8'))

    def test_discovery_requires_positive_progress_and_year_date(self):
        shelf={'books':[{'bookId':'two','title':'只是加入书架','updateTime':1767225600}]}
        with tempfile.TemporaryDirectory() as tmp:
            with patch('generate_reading_html.call',side_effect=[shelf,snapshot(2)['annual'],{'books':[]}, {'book':{'progress':0,'updateTime':1767225600}}]):
                result=collect_snapshot(2026,'secret',tmp)
            self.assertEqual(len(annual_data(result)['books']),1)

    def test_large_new_collection_requires_explicit_scope_before_book_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=snapshot(101)
            source['annual']['readLongest']=[{'book':{'bookId':str(i),'title':'示例书'},'readTime':120} for i in range(101)]
            source_path=root/'snapshot.json';source_path.write_text(json.dumps(source),'utf-8')
            with patch('sys.argv',['generate','--year','2026','--annual-snapshot',str(source_path),'--output',str(root/'index.html')]),patch.dict('os.environ',{'WEREAD_API_KEY':'secret'}),patch('generate_reading_html.collect') as request,patch('builtins.print'):
                self.assertEqual(main(),3);request.assert_not_called()


if __name__=='__main__':unittest.main()
