#!/usr/bin/env python3
"""Fresh composed 71EC screen oracle; actual 7334 runs without substitutions.

Native successes are complete original executions through 72CC. Resource
failures and unavailable-provider controls are separately labeled C controls.
GPL-3.0-only.
"""
import argparse
import ctypes as C
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from c_build_inputs import implementation_inputs

from test_boot_events_c import MODULES
from test_diagnostic_rom_status_c import (bind_event_api, compile_library,
    event_bytes, expected_stream, pin, stream_summary)

ROOT=Path(__file__).resolve().parents[1]
SUPPORT=ROOT/'tools/diagnostic_screen_support'
FIXTURE=ROOT/'analysis/native-fixtures/diagnostic-screen/inputs.json'
ROM=ROOT/'firmware/fx-991es-plus-c-ver4.bin'

def require(value,message):
    if not value: raise ValueError(message)

def digest(value): return hashlib.sha256(value).hexdigest()

def initial(seed,port):
    data=bytearray((a*17+seed*29+0x5a)&255 for a in range(65536))
    for a,v in [(0x811f,10),(0x8120,0),(0x8121,1),(0xf050,port)]:
        data[a]=v
    return bytes(data)

def image_for(stock,recipe):
    image=bytearray(stock)
    for item in recipe.get('metadata',[]):
        require(0x1fff4<=item['address']<=0x1fffb,'Executable/data patch outside declared version metadata')
        image[item['address']]=item['value']
    if recipe.get('checksum')=='matching':
        value=(-sum(image[:65536])-sum(image[65536:0x1fffc]))&65535
        image[0x1fffc:0x1fffe]=value.to_bytes(2,'little')
    elif recipe.get('checksum')=='mismatch':
        image[0x1fffc]^=1
    return bytes(image)

def original(output,env):
    target=output/'original.so'
    compile_library(['gcc','-std=c99','-O2','-Wall','-Wextra','-shared','-fPIC',
        '-I'+str(ROOT/'tools'),str(SUPPORT/'native.c'),
        str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),'-o',str(target)],
        output/'original-compile.json',env)
    lib=C.CDLL(str(target))
    for name,types in {
        'harness_init':[C.c_void_p,C.c_size_t],
        'harness_set_pc':[C.c_uint32],'harness_set_lr':[C.c_uint32],
        'harness_set_sp':[C.c_uint16],'harness_set_reg':[C.c_uint,C.c_uint8],
        'screen_native_run':[C.c_uint64,C.c_uint32]}.items():
        getattr(lib,name).argtypes=types
    for name in ['harness_ram','screen_native_mask','screen_native_flush_frames','screen_native_flush_events']:
        getattr(lib,name).restype=C.c_void_p
    bind_event_api(lib,'diagnostic_native')
    return lib

def candidate(output,opt,env):
    target=output/(opt+'.so')
    compile_library(['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror',
        '-shared','-fPIC','-Wl,--no-undefined',
        '-I'+str(ROOT/'csrc/platform'),str(SUPPORT/'candidate.c'),
        *[str(ROOT/'csrc'/ (m+'.c')) for m in MODULES],
        '-Wl,--wrap=fx_data_read','-Wl,--wrap=fx_diagnostic_rom_status_run',
        '-Wl,--wrap=fx_flush_framebuffer','-o',str(target)],
        output/(opt+'-compile.json'),env)
    lib=C.CDLL(str(target))
    lib.diagnostic_candidate_run.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,
        C.c_uint8,C.c_uint8,C.c_uint32,C.c_uint8,C.c_uint8,C.c_uint,C.c_uint,C.c_uint]
    lib.screen_candidate_prepared_label.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_uint8]
    for name in ['diagnostic_candidate_ram','screen_candidate_prefix',
        'screen_candidate_flush_frames','screen_candidate_flush_events']:
        getattr(lib,name).restype=C.c_void_p
    bind_event_api(lib,'diagnostic_candidate')
    return lib

def candidate_run(lib,image,data,cycle=0,sampled=0x44,retention=0,callbacks=15,present=1,platform=0):
    imagebuf=C.create_string_buffer(image); rambuf=C.create_string_buffer(data)
    status=lib.diagnostic_candidate_run(imagebuf,len(image),rambuf,0,0,cycle,
        sampled,retention,callbacks,present,platform)
    return {'status':status,'value':lib.diagnostic_candidate_value(),
        'ram':C.string_at(lib.diagnostic_candidate_ram(),65536),
        'prefix':C.string_at(lib.screen_candidate_prefix(),65536),
        'stream':event_bytes(lib,'diagnostic_candidate'),
        'frames':C.string_at(lib.screen_candidate_flush_frames(),3*384),
        'flush_events':list((C.c_uint32*3).from_address(lib.screen_candidate_flush_events())),
        'flush_count':lib.screen_candidate_flush_count(),
        'callback':lib.screen_candidate_callback()}

def compare_ram(actual,native,mask,label):
    diff=[a for a in range(65536) if not mask[a] and actual[a]!=native[a]]
    require(not diff,label+' full RAM/MMIO outside actual written live frames differs: '+repr([(hex(a),actual[a],native[a]) for a in diff[:20]]))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=None)
    args=parser.parse_args(); out=(args.output or ROOT/'analysis/build/diagnostic-boot-integration-review'/('actual-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))).resolve()
    require(not (out/'report.json').exists(),'Refusing to overwrite existing proof')
    out.mkdir(parents=True,exist_ok=True); temporary=out/'tmp';temporary.mkdir(exist_ok=True)
    env=dict(os.environ,TMPDIR=str(temporary))
    paths=[*[ROOT/name for name in implementation_inputs(ROOT,['csrc/'+m+'.c' for m in MODULES])],
        *ROOT.joinpath('tools/nxu8').rglob('*.c'),*ROOT.joinpath('tools/nxu8').rglob('*.h'),
        Path(__file__),FIXTURE,ROM,ROOT/'analysis/disassembly/complete.asm',ROOT/'csrc/CMakeLists.txt',
        ROOT/'tools/test_boot_events_c.py',ROOT/'tools/test_diagnostic_rom_status_c.py',
        *SUPPORT.glob('*.c'),ROOT/'tools/diagnostic_rom_status_support/native.c',
        ROOT/'tools/c_verification.py',ROOT/'tools/test_platform_c.py',
        ROOT/'tools/test_key_wait_c.py',ROOT/'tools/test_key_controller_c.py',
        ROOT/'tools/test_diagnostic_contrast_c.py',ROOT/'tools/test_key_wait_c.py']
    paths += [Path(module.__file__).resolve() for module in tuple(sys.modules.values()) if getattr(module,'__file__',None) and Path(module.__file__).resolve().is_relative_to(ROOT/'tools') and Path(module.__file__).suffix=='.py']
    before=pin(paths)
    for opt in ('O2','O3'):
        compile_library(['gcc','-std=c99','-'+opt,'-Wall','-Wextra','-Werror','-pedantic','-fsyntax-only',str(ROOT/'csrc/platform/fx_diagnostic_rom_status.c')],out/(opt+'-component-strict-compile.json'),env)
    fixture=json.loads(FIXTURE.read_text());stock=ROM.read_bytes()
    native=original(out,env);builds={o:candidate(out,o,env) for o in ('O2','O3')}
    artifacts_before={n:digest((out/n).read_bytes()) for n in ('original.so','O2.so','O3.so')}
    rows=[];pairs={o:[] for o in builds}
    for recipe in fixture['original_recipes']:
        image=image_for(stock,recipe);data=initial(recipe['seed'],recipe['port'])
        imagebuf=C.create_string_buffer(image)
        native.harness_init(imagebuf,len(image))
        C.memmove(native.harness_ram(),data,65536)
        for n in range(16): native.harness_set_reg(n,(n*13+recipe['seed']*17)&255)
        native.harness_set_sp(0x8dee);native.harness_set_lr(0x2fffe);native.harness_set_pc(0x71ec)
        native.screen_native_clear()
        require(native.screen_native_run(4000000,0x7282)==100,'Original prefix did not reach true 7334 call')
        prefix=C.string_at(native.harness_ram(),65536)
        prefixmask=C.string_at(native.screen_native_mask(),65536)
        require(native.diagnostic_native_event_count()==0,'Read test ran before prefix boundary')
        require(native.screen_native_flush_count()==2,'Original prefix flush count')
        prefixcallback=native.harness_callback()
        require(native.screen_native_run(4000000,0x72cc)==100,'Composed original did not reach true suffix service boundary')
        final=C.string_at(native.harness_ram(),65536);mask=C.string_at(native.screen_native_mask(),65536)
        frames=C.string_at(native.screen_native_flush_frames(),3*384)
        flushevents=list((C.c_uint32*3).from_address(native.screen_native_flush_events()))
        stream=event_bytes(native,'diagnostic_native')
        expected,value,reads=expected_stream(image)
        require(stream==expected and value==0xa5 and reads==131068,'Actual original ordered resources/ROM differ')
        require(native.screen_native_flush_count()==3 and flushevents==[0,0,393206],'Original complete display/read ordering')
        callback=native.harness_callback()
        require(final[0xf049:0xf04d]==bytes([1,1,1,0]),'Actual suffix keyport values')
        counts=(C.c_uint64*0x18000).in_dll(native,'execution_counts')
        require(counts[0x7334>>1]==1 and not counts[0x737e>>1],'Original read body not genuinely executed')
        files={}
        for label,blob in [('prefix',prefix),('prefix-mask',prefixmask),('final',final),('frame-mask',mask),('flushes',frames),('transactions',stream)]:
            path=out/(recipe['id']+'-'+label+'.bin');path.write_bytes(blob)
            files[label]={'file':path.name,'sha256':digest(blob),'bytes':len(blob)}
        row={'id':recipe['id'],'recipe':recipe,'rom_sha256':digest(image),'initial_ram_sha256':digest(data),
            'native_steps':sum(counts),'native_read_entry_visits':counts[0x7334>>1],
            'prefix_pc':0x7282,'suffix_pc':0x72cc,'prefix_callback':prefixcallback,
            'callback':callback,'flush_event_indices':flushevents,'stream':stream_summary(stream),
            'actual_frame_written_addresses':[a for a in range(65536) if mask[a]],'files':files}
        rows.append(row)
        for opt,lib in builds.items():
            actual=candidate_run(lib,image,data)
            require((actual['status'],actual['value'])==(0,0xa5),'C complete status/value differs')
            compare_ram(actual['prefix'],prefix,prefixmask,recipe['id']+' '+opt+' prefix')
            compare_ram(actual['ram'],final,mask,recipe['id']+' '+opt+' suffix')
            require(actual['stream']==stream,'C complete ordered resources/ROM differ')
            require(actual['frames']==frames and actual['flush_count']==3 and actual['flush_events']==flushevents,'C flush frame/order differs')
            require(actual['callback']==callback==prefixcallback,'C/native callbacks differ')
            candidate_files={}
            for checkpoint in ('prefix','ram'):
                path=out/(recipe['id']+'-'+opt+'-'+checkpoint+'.bin');path.write_bytes(actual[checkpoint])
                candidate_files[checkpoint]={'file':path.name,'sha256':digest(actual[checkpoint]),'bytes':65536}
            pairs[opt].append({'files':candidate_files,'id':recipe['id'],'status':0,'value':0xa5,
                'prefix_ram_equal':True,'suffix_ram_equal':True,'all_ordered_transactions_equal':True,
                'all_three_flush_frames_equal':True,'stream_sha256':digest(actual['stream']),
                'prefix_sha256':digest(actual['prefix']),'final_sha256':digest(actual['ram'])})
        print('original and O2/O3 complete:',recipe['id'],flush=True)
    controls={o:[] for o in builds}
    data=initial(91,3)
    for opt,lib in builds.items():
        for cycle in fixture['modeled_fault_cycles']+[0]:
            retention=int(cycle==0)
            actual=candidate_run(lib,stock,data,cycle=cycle,sampled=0,retention=retention)
            expected,value,reads=expected_stream(stock,cycle,0,bool(retention))
            require(actual['status']==0 and actual['value']==value==0 and actual['stream']==expected,'Modeled resource fault semantics')
            require(actual['flush_count']==3 and actual['flush_events']==[0,0,len(expected)//5],'Modeled failure display ordering')
            failedram=actual['ram'];failedframes=actual['frames']
            imagebuf=C.create_string_buffer(stock);rambuf=C.create_string_buffer(data)
            lib.screen_candidate_prepared_label(imagebuf,len(stock),rambuf,0)
            require(C.string_at(lib.diagnostic_candidate_ram(),65536)==failedram,'Modeled failure must display explicit Read NG helper output')
            require(C.string_at(lib.screen_candidate_flush_frames(),1152)==failedframes,'Modeled Read NG helper flush images')
            controls[opt].append({'kind':'modeled_retention_failure' if retention else 'modeled_status_failure',
                'cycle':cycle,'status':0,'value':0,'reads':reads,'stream_sha256':digest(expected),
                'read_ng_matches_prepared_c_label_helper':True,'native_failure_execution':False})
        for callbacks,present,platform in [(m,1,0) for m in range(15)]+[(15,0,0),(15,1,1),(15,1,2),(15,1,3)]:
            actual=candidate_run(lib,stock,data,callbacks=callbacks,present=present,platform=platform)
            expectedstatus=-1 if platform else -2
            require(actual['status']==expectedstatus and actual['ram']==data and not actual['stream'] and actual['flush_count']==0 and not actual['callback'],'Unavailable/invalid screen API produced writes or firmware failure label')
            controls[opt].append({'kind':'invalid_platform' if platform else 'unavailable_resources',
                'callbacks':callbacks,'present':present,'platform':platform,'status':expectedstatus,
                'all_ram_unchanged':True,'flushes':0,'resource_events':0,'not_read_ng':True})
    after=pin(paths);artifacts_after={n:digest((out/n).read_bytes()) for n in artifacts_before}
    require(before==after,'Source drift within actual execution')
    require(artifacts_before==artifacts_after,'Compiled artifact drift within actual execution')
    require([{k:v for k,v in row.items() if k!='files'} for row in pairs['O2']]==[{k:v for k,v in row.items() if k!='files'} for row in pairs['O3']] and controls['O2']==controls['O3'],'Optimized builds disagree')
    report={'schema':1,'status':'pass','utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_pins_before':before,'source_pins_after':after,
        'artifacts_before':artifacts_before,'artifacts_after':artifacts_after,
        'original_executions':len(rows),'candidate_comparisons':2*len(rows),
        'full_ram_checkpoints':4*len(rows),'original_rows':rows,'candidate_builds':pairs,
        'modeled_controls':controls,'modeled_controls_per_build':len(controls['O2']),
        'evidence_boundaries':{'actual_71ec_including_7334':True,
            'no_post_entry_cpu_inputs_or_instruction_replacement':True,
            'native_success_only':True,'native_failure_execution':False,
            'full_boot_or_hardware_certification':False,'fault_labels_are_c_provider_controls':True,
            'ram_exclusion_only_actual_written_live_frames':True,
            'stop_before_actual_5550_service':True}}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'pass','report':str(out/'report.json'),
        'sha256':digest((out/'report.json').read_bytes()),'originals':len(rows),
        'comparisons':len(rows)*2,'modeled_controls_per_build':len(controls['O2']),
        'source_pins':len(before)},indent=2))

if __name__=='__main__': main()
