"""Portable evidence-checked results. Integrity hashes are not semantic certification."""
import copy
import hashlib
import json
import re
from pathlib import Path
from ebook_reading import _sources, validate_context, validate_review

READING_FIELDS_CONTRACT = ('Optional reading_lenses:[{id,kind:values|tone|tension|connections,title,text,sources}] '
    'and memorable_passages:[{text,why_it_matters,sources}]. Choose relevant lenses only; support interpretations '
    'with evidence and never infer private author motives. Passage text must be an exact contiguous original '
    'quotation in its cited element AND quote; title mode only source_type=preview may supply original passages, '
    'never secondary paraphrases or source_notes. Empty optional lists are valid; literature needs no invented methods.')

# Every public object has an explicit shape, including objects below optional
# reader fields. Scalar leaves cannot carry arbitrary nested pipeline payloads.
BOOK = {'id':str,'title':str,'author':str,'edition':str,'identity_url':str}
SOURCE = {'element_id':str,'quote':str,'location':str,'url':str,'source_type':str,'source_id':str}
VERIFICATION = {'status':str,'reason':str,'V1':bool,'V2':bool,'V3':bool,
    'source_sufficiency':{'reason':str},
    'walkthrough':{'input':str,'steps':[str],'output':str,'completion_standard':str},
    'task_utility':str,'pressure_passed':bool,'source_check':str,'semantic_evaluation':str,'blind_baseline':bool}
READER_ENTRY = {'id':str,'title':str,'explanation':str,'sources':[SOURCE],'source_verified':bool}
METHOD = {'id':str,'title':str,'interpretation':str,'trigger':str,'steps':[str],'example':str,
    'boundaries':[str],'candidate_ids':[str],'original_candidate_ids':[str],
    'sources':[SOURCE],'source_verified':bool,'verification':VERIFICATION}
CANDIDATE = {'id':str,'title':str,'type':str,'summary':str,'status':str,'reason':str,'task_ids':[str],
    'sources':[SOURCE],'verification':VERIFICATION,'canonical_id':str,'coverage_reason':str,
    'original_candidate_ids':[str],'delivered_methods':[str],'delivered_reference':(str,type(None)),'final_status':str}
PUBLIC_SCHEMA = {'schema_version':int,'book':BOOK,'overview':str,
    'book_context':[{**READER_ENTRY,'kind':str}], 'themes':[READER_ENTRY],'methods':[METHOD],
    'cases':[{**READER_ENTRY,'case_origin':str}],'counterexamples':[READER_ENTRY],
    'glossary':[{'term':str,'definition':str,'sources':[SOURCE],'source_verified':bool}],
    'limitations':[str],'insights':[READER_ENTRY],
    'topic_coverage':[{'topic_id':str,'status':str,'item_refs':[str],'reason':str}],
    'source_hash':str,'input_mode':str,'quality_status':str,
    'coverage':{'complete':bool,'full_text':bool,'scope_note':str,'chunks_total':int,'chunks_processed':int,
        'warnings':[str],'sources_read':int,'genre':str,
        'key_tasks':[{'id':str,'title':str,'sources':[SOURCE]}],
        'task_audit':[{'task_id':str,'status':str,'candidate_ids':[str],'reason':str}],
        'candidate_dispositions':[CANDIDATE],
        'excluded_boilerplate':[{'kind':str,'wrapper_id':str}]},
    'reading_lenses':[{'id':str,'kind':str,'title':str,'text':str,'sources':[SOURCE],'source_verified':bool}],
    'memorable_passages':[{'text':str,'why_it_matters':str,'sources':[SOURCE],'source_verified':bool}],
    'content_map':[{'id':str,'title':str,'importance':str,'status':str,'sources':[SOURCE],'gap':str}],
    'reading_status':{'level':str,'label':str,'reason':str},
    'review':{'status':str,'reason':str,'paragraphs':[{'text':str,'sources':[SOURCE],'quotes':[SOURCE]}]},
    'references':[{'id':str,'title':str,'summary':str,'sources':[SOURCE],
        'original_candidate_ids':[str],'source_verified':bool,'verification':VERIFICATION}],
    'pipeline_version':str,'evaluation_limit':str,
    'structure_index':[{'title':str,'element_ids':[str]}],
    'decision_rules':[{**METHOD,'method_id':str}], 'source_notice':str,
    'bibliography':[{'id':str,'url':str,'title':str,'type':str,'accessed_at':str,
        'content_hash':str,'content_kind':str}]}
CHECKS_SCHEMA = {'book':BOOK,'source_hash':str,'input_mode':str,'source_validation':str,
    'semantic_validation':str,'evidence':[{'element_id':str,'quote_hash':str,'location':str,'source_type':str}]}
PUBLIC_FIELDS = set(PUBLIC_SCHEMA)


def _public(value, schema=PUBLIC_SCHEMA):
    if isinstance(schema,dict):
        if not isinstance(value,dict): raise ValueError('Invalid public object')
        return {key:_public(item,schema[key]) for key,item in value.items() if key in schema}
    if isinstance(schema,list):
        if not isinstance(value,list): raise ValueError('Invalid public list')
        return [_public(item,schema[0]) for item in value]
    allowed=schema if isinstance(schema,tuple) else (schema,)
    if type(value) not in allowed: raise ValueError('Invalid public scalar')
    return value


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def bundle_hash(bundle):
    return _hash({key:value for key,value in bundle.items() if key != 'bundle_hash'})


def validate_reading_fields(analysis, elements, mode):
    index = {e['element_id']:e for e in elements}
    for key in ('reading_lenses','memorable_passages'):
        rows=analysis.get(key, [])
        if not isinstance(rows,list): raise ValueError('Invalid '+key)
        seen=set()
        for row in rows:
            if not isinstance(row,dict): raise ValueError('Invalid '+key+' entry')
            fields=('id','kind','title','text') if key=='reading_lenses' else ('text','why_it_matters')
            if any(not isinstance(row.get(k),str) or not row[k].strip() for k in fields): raise ValueError('Empty reading field')
            _sources(row.get('sources'),elements)
            if key=='reading_lenses':
                if row['kind'] not in ('values','tone','tension','connections') or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',row['id']) or row['id'] in seen: raise ValueError('Invalid reading lens identity/kind')
                seen.add(row['id'])
            else:
                if not any(row['text'] in s['quote'] and row['text'] in index[s['element_id']]['text'] for s in row['sources']): raise ValueError('Passage is not an exact cited quotation')
                if mode=='title' and any(index[s['element_id']].get('source_type')!='preview' for s in row['sources']): raise ValueError('Public secondary material is not original book text')
            row['source_verified']=True


def _citations(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ('sources','quotes'):
                if not isinstance(item,list): raise ValueError('Invalid citation list')
                yield from item
            else: yield from _citations(item)
    elif isinstance(value,list):
        for item in value: yield from _citations(item)


def _base(analysis):
    from ebook_pipeline import _analysis_contract
    if not isinstance(analysis,dict): raise ValueError('Invalid analysis')
    _analysis_contract(analysis)
    for category,fields in (('themes',('title','explanation')),('cases',('title','explanation')),
        ('counterexamples',('title','explanation')),('glossary',('term','definition')),
        ('methods',('title','interpretation','trigger','example')),('insights',('title','explanation'))):
        for row in analysis.get(category,[]):
            if not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not row[k].strip() for k in fields): raise ValueError('Empty reader content')
    if not analysis['book']['title'].strip(): raise ValueError('Missing book identity')
    if analysis.get('input_mode') not in ('upload','title'): raise ValueError('Invalid input mode')
    if not re.fullmatch('[a-f0-9]{64}', str(analysis.get('source_hash',''))): raise ValueError('Invalid source hash')
    coverage=analysis.get('coverage')
    if not isinstance(coverage,dict) or not isinstance(coverage.get('complete'),bool) or not isinstance(coverage.get('scope_note'),str) or not coverage['scope_note'].strip(): raise ValueError('Missing coverage boundary')
    if analysis['input_mode']=='title' and (coverage.get('full_text') is not False or coverage['complete']): raise ValueError('Public sources cannot claim full-text coverage')
    if analysis.get('quality_status') not in ('completed','needs_review'): raise ValueError('Unfinished analysis')
    return analysis


def make_bundle(analysis, document, digest=''):
    analysis=_public(analysis)
    _base(analysis)
    if not isinstance(document,dict) or analysis['source_hash']!=document.get('source_hash') or analysis['book']!=_public(document.get('book'),BOOK): raise ValueError('Source/book binding mismatch')
    if document.get('input_mode',analysis['input_mode'])!=analysis['input_mode']: raise ValueError('Source mode mismatch')
    if analysis['input_mode']=='upload' and ('bibliography' in document or any(e.get('source_type') in ('author','publisher','preview','interview','secondary') for e in document.get('elements',[]))): raise ValueError('Public sources cannot be relabelled uploaded text')
    elements=document.get('elements')
    if not isinstance(elements,list) or not elements: raise ValueError('Missing source evidence')
    if analysis['input_mode']=='title' and any(e.get('source_type') not in ('author','publisher','preview','interview','secondary') for e in elements): raise ValueError('Public-source elements need their source type')
    index={e['element_id']:e for e in elements}
    if len(index)!=len(elements): raise ValueError('Duplicate source identity')
    for key in ('themes','methods','cases','counterexamples','glossary','references','insights'):
        for row in analysis.get(key,[]): _sources(row.get('sources'),elements)
    validate_context(analysis,elements)
    validate_reading_fields(analysis,elements,analysis['input_mode'])
    if 'review' in analysis: validate_review(analysis['review'],elements,set(index))
    evidence=[]
    for citation in _citations(analysis):
        _sources([citation],elements)
        record={'element_id':citation['element_id'],'quote_hash':_hash(citation['quote']),
                'location':citation['location'],'source_type':index[citation['element_id']].get('source_type','text')}
        if record not in evidence: evidence.append(record)
    # Only public reader fields leave the private pipeline.
    analysis=_public({key:value for key,value in analysis.items() if key in PUBLIC_FIELDS})
    bundle={'schema_version':1,'kind':'reading-distillation','analysis':analysis,'digest':digest,
            'source_hash':analysis['source_hash'],'input_mode':analysis['input_mode'],
            'source_mode':document.get('source_mode','real'),
            'checks':{'book':copy.deepcopy(analysis['book']),'source_hash':analysis['source_hash'],
                      'input_mode':analysis['input_mode'],'source_validation':'exact_quotes',
                      'semantic_validation':'not_independent','evidence':evidence}}
    bundle['bundle_hash']=bundle_hash(bundle)
    return validate_bundle(bundle)


def validate_bundle(bundle):
    try:
        if not isinstance(bundle,dict) or set(bundle)!= {'schema_version','kind','analysis','digest','source_hash','input_mode','source_mode','checks','bundle_hash'}: raise ValueError('Invalid result bundle fields')
        if type(bundle['schema_version']) is not int or bundle['schema_version']!=1 or bundle['kind']!='reading-distillation' or bundle['source_mode'] not in ('real','sample') or not isinstance(bundle['digest'],str): raise ValueError('Invalid result bundle schema')
        if bundle_hash(bundle)!=bundle['bundle_hash']: raise ValueError('Result bundle integrity mismatch')
        analysis=_base(bundle['analysis']); checks=bundle['checks']
        if set(analysis)-PUBLIC_FIELDS or _public(analysis)!=analysis: raise ValueError('Private fields in public result')
        if not isinstance(checks,dict) or _public(checks,CHECKS_SCHEMA)!=checks or checks.get('source_validation')!='exact_quotes' or checks.get('semantic_validation')!='not_independent': raise ValueError('Missing source checks')
        for key in ('source_hash','input_mode'):
            if bundle[key]!=analysis[key] or checks.get(key)!=analysis[key]: raise ValueError('Result bundle binding mismatch')
        if checks.get('book')!=analysis['book']: raise ValueError('Book identity binding mismatch')
        evidence=checks.get('evidence')
        if not isinstance(evidence,list) or not evidence: raise ValueError('Missing checked evidence')
        for citation in _citations(analysis):
            if not isinstance(citation,dict) or not all(isinstance(citation.get(k),str) and citation[k] for k in ('element_id','quote','location')): raise ValueError('Invalid public citation')
            if not any(e.get('element_id')==citation['element_id'] and e.get('quote_hash')==_hash(citation['quote']) and e.get('location')==citation['location'] for e in evidence): raise ValueError('Unchecked public citation')
        # Reapply optional reader structure and exact passage/secondary boundaries using
        # checked short quotations; full source text is deliberately not in this file.
        public_elements=[]
        for e in evidence:
            quotes=[s['quote'] for s in _citations(analysis) if s['element_id']==e['element_id']]
            public_elements.append({'element_id':e['element_id'],'text':'\n'.join(quotes),'location':e['location'],'source_type':e.get('source_type')})
        for key in ('themes','methods','cases','counterexamples','glossary','references','insights'):
            for row in analysis.get(key,[]): _sources(copy.deepcopy(row.get('sources')),public_elements)
        validate_context(copy.deepcopy(analysis),public_elements)
        validate_reading_fields(copy.deepcopy(analysis),public_elements,analysis['input_mode'])
        if 'review' in analysis:
            validate_review(copy.deepcopy(analysis['review']),public_elements,{e['element_id'] for e in public_elements})
        return bundle
    except (KeyError,TypeError,AttributeError,OverflowError) as error:
        raise ValueError('Invalid result bundle structure') from error


def load_bundle(path):
    from ebook_agent import strict_json
    path=Path(path)
    if path.stat().st_size>32*1024*1024: raise ValueError('Result bundle exceeds 32 MB')
    return validate_bundle(strict_json(path.read_text('utf-8')))
