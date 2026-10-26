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

PUBLIC_FIELDS = {'schema_version','book','overview','book_context','themes','methods','cases','counterexamples',
    'glossary','limitations','insights','topic_coverage','source_hash','input_mode','quality_status','coverage',
    'reading_lenses','memorable_passages','content_map','reading_status','review','references','pipeline_version',
    'evaluation_limit','structure_index','decision_rules','source_notice','bibliography'}
PRIVATE_FIELDS = {'execution_identity','token','api_key','credentials','password','prompt','audit','stages',
    'actual_task_trials','source_notes','document','elements'}


def _public(value):
    if isinstance(value,dict): return {k:_public(v) for k,v in value.items() if k not in PRIVATE_FIELDS}
    if isinstance(value,list): return [_public(v) for v in value]
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
    analysis=copy.deepcopy(analysis)
    _base(analysis)
    if not isinstance(document,dict) or analysis['source_hash']!=document.get('source_hash') or analysis['book']!=document.get('book'): raise ValueError('Source/book binding mismatch')
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
        if not isinstance(checks,dict) or checks.get('source_validation')!='exact_quotes' or checks.get('semantic_validation')!='not_independent': raise ValueError('Missing source checks')
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
        return bundle
    except (KeyError,TypeError,AttributeError,OverflowError) as error:
        raise ValueError('Invalid result bundle structure') from error


def load_bundle(path):
    from ebook_agent import strict_json
    path=Path(path)
    if path.stat().st_size>32*1024*1024: raise ValueError('Result bundle exceeds 32 MB')
    return validate_bundle(strict_json(path.read_text('utf-8')))
