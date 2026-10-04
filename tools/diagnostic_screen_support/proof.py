#!/usr/bin/env python3
"""Read-only recomputation of composed diagnostic-screen archive custody."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from test_diagnostic_screen_c import image_for, initial
from test_diagnostic_rom_status_c import expected_stream

def require(value,message):
    if not value: raise ValueError(message)
def digest(value): return hashlib.sha256(value).hexdigest()
def blob(folder,item):
    value=(folder/item['file']).read_bytes()
    require(len(value)==item['bytes'] and digest(value)==item['sha256'],'Archive digest/size differs: '+item['file'])
    return value
def verify(report,folder):
    require(report['status']=='pass','Report not PASS')
    require(report['source_pins_before']==report['source_pins_after'],'In-run source drift')
    for path,wanted in report['source_pins_before'].items():
        require(digest((ROOT/path).read_bytes())==wanted,'Current source drift: '+path)
    require(report['artifacts_before']==report['artifacts_after'],'In-run compiled artifact drift')
    for path,wanted in report['artifacts_before'].items():
        require(digest((folder/path).read_bytes())==wanted,'Current artifact drift: '+path)
    fixture=json.loads((ROOT/'analysis/native-fixtures/diagnostic-screen/inputs.json').read_text())
    recipes=fixture['original_recipes'];rows=report['original_rows']
    require(len(rows)==len(recipes)==report['original_executions']==7,'Original census differs')
    require(report['candidate_comparisons']==14 and report['full_ram_checkpoints']==28,'Pair/checkpoint census differs')
    stock=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    observations={}
    for recipe,row in zip(recipes,rows):
        require(row['recipe']==recipe and row['id']==recipe['id'],'Authored recipe/order differs')
        image=image_for(stock,recipe);data=initial(recipe['seed'],recipe['port'])
        require(digest(image)==row['rom_sha256'] and digest(data)==row['initial_ram_sha256'],'Authored input hashes differ')
        files={key:blob(folder,item) for key,item in row['files'].items()}
        require(set(files)=={'prefix','prefix-mask','final','frame-mask','flushes','transactions'},'Original archive set differs')
        expected,value,reads=expected_stream(image)
        require(files['transactions']==expected and value==0xa5 and reads==131068,'Complete archived ROM/resource stream differs')
        require(row['stream']['sha256']==digest(expected) and row['stream']['event_count']==393206,'Resource stream summary differs')
        for name in ('prefix-mask','frame-mask'):
            require(len(files[name])==65536 and set(files[name])<={0,1},'Invalid actual live-frame mask')
        require(all(not a or b for a,b in zip(files['prefix-mask'],files['frame-mask'])),'Prefix frame writes missing from cumulative mask')
        require([a for a in range(65536) if files['frame-mask'][a]]==row['actual_frame_written_addresses'],'Frame exclusion differs')
        require(all(0x8000<=a<0x8dee for a in row['actual_frame_written_addresses']),'Frame mask includes non-frame RAM')
        require(row['prefix_pc']==0x7282 and row['suffix_pc']==0x72cc and row['native_read_entry_visits']==1,'Native complete entry/checkpoints differ')
        require(row['flush_event_indices']==[0,0,393206] and row['prefix_callback']==row['callback']==0,'Original display/resource/callback ordering differs')
        require(files['final'][0xf049:0xf04d]==bytes([1,1,1,0]),'Original suffix keyport state differs')
        require(files['flushes'][384:768]==files['prefix'][0x87d0:0x8950]
                and files['flushes'][768:1152]==files['final'][0x87d0:0x8950],'Final/prefix original display updates differ')
        for snapshot in ('prefix','final'):
            framebuffer=files[snapshot][0x87d0:0x8950]
            for y in range(32):
                require(files[snapshot][0xf800+16*y:0xf80c+16*y]==framebuffer[12*y:12*y+12],'Original LCD copy differs')
        observations[row['id']]=files
    require(set(report['candidate_builds'])=={'O2','O3'},'Missing optimized build')
    for opt,pairs in report['candidate_builds'].items():
        require([pair['id'] for pair in pairs]==[r['id'] for r in recipes],'Pair order/census differs')
        for pair in pairs:
            files=observations[pair['id']]
            require(pair['status']==0 and pair['value']==0xa5 and pair['prefix_ram_equal']
                and pair['suffix_ram_equal'] and pair['all_ordered_transactions_equal']
                and pair['all_three_flush_frames_equal'],'Pair semantics differs')
            for name,maskname,native,hashname in [('prefix','prefix-mask','prefix','prefix_sha256'),('ram','frame-mask','final','final_sha256')]:
                value=blob(folder,pair['files'][name])
                require(digest(value)==pair[hashname],'C observation hash differs')
                require(all(files[maskname][a] or value[a]==files[native][a] for a in range(65536)),
                    'Recomputed full RAM outside actual written frame differs')
            require(pair['stream_sha256']==digest(files['transactions']),'C/native ordered stream binding differs')
    controls=report['modeled_controls']
    require(set(controls)=={'O2','O3'} and controls['O2']==controls['O3'],'Modeled optimized builds disagree')
    for opt,items in controls.items():
        require(len(items)==report['modeled_controls_per_build']==24,'Modeled/API census differs')
        for item in items:
            if item['kind'].startswith('modeled_'):
                retention=item['kind']=='modeled_retention_failure'
                events,value,reads=expected_stream(stock,item['cycle'],0,retention)
                require(item['status']==0 and item['value']==value==0 and item['reads']==reads
                    and item['stream_sha256']==digest(events) and item['read_ng_matches_prepared_c_label_helper']
                    and item['native_failure_execution'] is False,'Modeled failure relabeled or changed')
            else:
                require(item['kind'] in ('invalid_platform','unavailable_resources'),'Unknown API control')
                require(item['status']==(-1 if item['platform'] else -2)
                    and item['all_ram_unchanged'] and item['flushes']==item['resource_events']==0 and item['not_read_ng'],
                    'Unavailable/invalid input relabeled as Read NG or writes')
    boundaries=report['evidence_boundaries']
    require(boundaries['actual_71ec_including_7334'] and boundaries['no_post_entry_cpu_inputs_or_instruction_replacement']
        and boundaries['native_success_only'] and not boundaries['native_failure_execution']
        and not boundaries['full_boot_or_hardware_certification'] and boundaries['fault_labels_are_c_provider_controls']
        and boundaries['ram_exclusion_only_actual_written_live_frames'] and boundaries['stop_before_actual_5550_service'],
        'Evidence boundary differs')
    return {'originals':7,'optimized_pairs':14,'recomputed_full_ram_checkpoints':28,
        'archived_original_resource_events':393206*7,'modeled_controls_per_build':24,
        'current_source_pins':len(report['source_pins_before']),'compiled_artifacts':3}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report',type=Path)
    args=parser.parse_args();path=args.report.resolve();report=json.loads(path.read_text())
    summary=verify(report,path.parent)
    mutations=[]
    for label,edit in [
        ('source_pin',lambda r:r['source_pins_before'].__setitem__('tools/test_diagnostic_screen_c.py','0'*64)),
        ('native_archive_pin',lambda r:r['original_rows'][0]['files']['transactions'].__setitem__('sha256','0'*64)),
        ('candidate_archive_pin',lambda r:r['candidate_builds']['O3'][0]['files']['ram'].__setitem__('sha256','0'*64)),
        ('native_read_entry',lambda r:r['original_rows'][0].__setitem__('native_read_entry_visits',0)),
        ('provider_missing_writes',lambda r:r['modeled_controls']['O2'][5].__setitem__('flushes',3)),
        ('hardware_scope',lambda r:r['evidence_boundaries'].__setitem__('full_boot_or_hardware_certification',True))]:
        altered=copy.deepcopy(report);edit(altered)
        try:verify(altered,path.parent)
        except ValueError:mutations.append(label)
        else:raise ValueError('Admitted forged '+label)
    output={'schema':1,'status':'pass','kind':'read-only archived evidence recomputation; no execution',
        'report_sha256':digest(path.read_bytes()),'checker_sha256':digest(Path(__file__).read_bytes()),
        'checks':summary,'negative_controls_rejected':mutations}
    target=path.parent/'custody.json';target.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({'status':'pass','custody':str(target),'sha256':digest(target.read_bytes()),'checks':summary,'negative_controls':len(mutations)},indent=2))
if __name__=='__main__':main()
