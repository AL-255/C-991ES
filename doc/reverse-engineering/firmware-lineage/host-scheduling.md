# Original Windows emulator STOP, keys and timer contract

This is a static audit of the Ver.4.00 payload, using 7z, objdump, section bytes and the firmware decoder. **No Windows binary was executed.** PE addresses are preferred-image VAs (EXE base 00400000, DLLs 10000000); ASLR can relocate them. Exact input hashes are in [PROVENANCE.md](PROVENANCE.md).

Firmware 538A/53D0 requests STOP through simulator SFRs. Engine detects the writes after an emulated instruction and reports run reason 2. SimU8 synchronously invokes the host callback; host services request 8E00 and sets F014 completion bits; runner releases STOP and CPU later accepts the interrupt. This is not evidence of a free-running physical timer.

## Registration and worker

EXE 41364E..413654 passes callback 413A70 and GUI subobject+7C as context to SetCallbackFunc (IAT 4841D4). 41365A calls SetWait(0). Callback ret 8 accepts(unsigned reason, void*context). SimU8 SetCallbackFunc 10001C00 stores pointer/context at 1016D92C/1016D930; SetWait 10001D30 stores 16-bit setting 1016D934, with setup rejected while running.

Worker 10005930 is created/resumed through SimStart 100062C0 → 10006240. It releases simulator synchronization at 10005A7B..10005A88 before direct callback 10005A99..10005AAA. That permits exported memory operations and concurrent GUI enqueue; next instruction executes only after callback return.

## STOP and interrupt boundaries

538A writes F024=1, F022=0, F020=caller_period, F025=1, F014/F015=0, then F008=50, F008=A0, F009=2. 53D0 instead preserves other flags while clearing F014 bit 1, then the same unlock/STOP sequence.

Engine execute 10005330 recognizes F008 state 0 → 1 for 50 at 100073A4..100073BF, then 1 → 2 forA0 at 1000759B..100075AA; invalid sequences reset. It consumes F008, checks unlocked F009 bit 1 at 100075D0..100075F6, and sets core+B9=2. Invalid STOP clears F009 bit 1; unlock state resets after handling. Core instance 1016CE20 makes reason byte 1016CED9.

Runner 10005A55..10005A65 executes an instruction and reads reason. While stopped it calls m_CheckInterrupt 10003E80 rather than executing. That routine checks enabled registered flags and clears core+B9 and F009 low bits at 10003EFA..10003F0D, **retaining F014**.

Actual CPU acceptance in execute's peripheral tail checks masks/interrupt enable/level, loads the selected vector, then 10007376..10007381 clears only the accepted F014 bit. Vector 000A (key) and 0012 (timer) both point to 6F80 whose opcode 0FFE is RTI; the ISR itself does not clear flags.

Preserve three boundaries in a readable scheduler:

1. Host service sets completion F014 bit 1 or 5.
2. STOP release clears F009 low bits but retains F014.
3. CPU acceptance clears the selected F014 bit before shared RTI.

EXE 413150..4135E3 registers 13 vectors. Relevant XI0INT is vector 0A, F010/F014 bit 1; TM0INT is vector 12, bit 5. Engine WriteBitDataMemory 100050DC..100050F6 takes a **bit index**, not a mask:arg 2&7 shifts 1, arg 3&1 selects set/clear.

## Host service dispatcher

Callback 413A70 clearscontext+10 on entry. Reason 2 reads 8E00; reasons 1/3/4 only record the reason and return.

| 8E00 | Handler | Completion effects |
| --- | --- | --- |
| 1 | 4137A0 keywait | Queued key:raw 8E01/02, F014 bit 1; idle:zero 8E01/02, F014 bit 5 |
| 2 | 413910 cancellation | Write 8E00 response 0/1, set F014 bit 5 |
| 3 | Inline 413ACB..413AF1 | SendMessageW(hwnd,467,0,0), set F014 bit 5 |
| 4 | 4138D0 notification | Read 512 bytes F800 to context+20, WM_PAINT, set F014 bit 5 |
| Other, including 0 | 4139B0 delay | Sleep conversion, set F014 bit 5, zero 8E01/02 |

These paths clearcontext+1C on completion. Notification does not write 8E00 or clear key bytes; cancellation does not write key bytes. Preserve those distinctions.

## Key queue, ON and cancellation

Context+00/+04 point to DWORD column/row arrays;+08=count;+0C=capacity;+14=queue synchronization;+18=hwnd;+20=display 512 bytes. GUI enqueue 40F114..40F152 appends a raw matrix pair. This is a software queue, not direct F040 sampling.

Keywait snapshots F800 and sends WM_PAINT, switches default completion tobit 5, then polls an empty queue with literal Sleep(15), up to 30 idle passes (4137EE..413803). Idlecompletion zeros 8E01/02 and setsbit 5. Queued completion pops the first pair, shifts arrays and decrements count under synchronization (41384D..413898), writes low columns to 8E01/rows to 8E02 and setsbit 1. The host does not complement column bytes.

p16 IsOnKeyCode 10001250 accepts only columns 0, rows 0. GUI interceptsON before enqueue; queued ON also callsreset 413730, clearingqueue/key bytes/snapshot/F800 and SimReset. It is a reset action, not ordinary 0/0 input.

Cancellation first snapshots/paints and setscontext+10=1, then 410EE0 dequeues **one** pair. p16 IsAcKeyCode 10001290 accepts columns 4, rows 16. AC clearscontext+10, discards remaining queue and selects response 1; empty or non-AC selects 0. A non-AC key was already consumed and is discarded. Handler writes 8E00 response and sets F014 bit 5. Firmware 5550 requests service 2 with period 129A, interprets nonzero as raw AC(4,16), and clears 8E00. Cancellation is separate from keywait.

## Delay conversion and precision caveat

Default handler 4139B0 reads unsigned 16-bit F020/F021 and multiplies by binary64 constant at 487728, bytesE17A14AE47E1BA3F, or 0.105. Positive products truncate toward zero only after the multiply; nonpositive takes Sleep argument 1. Thus period 0 → Sleep(1), periods 1..9 → Sleep(0).

The exact constant is 7566047373982433/72057594037927936, slightly below 21/200. Exhaustive rational modeling of 65536 periods under round-to-nearest gives:

| x87 significand precision | Equivalent integer result for positive periods |
| --- | --- |
| 53 bits | floor(105*n/1000), all inputs |
| 64 bits | floor(105*n/1000)−1 when n is a positive multiple 200;327 differences |

For period 200 this is 21 versus 20;1000 → 105 versus 104. EXE 4824AE..4824C3 and DLL 10104153..10104168 call _controlfp_s(NULL,10000,30000), selecting runtime 53-bit precision. Worker is created through DLL thread helper/CreateThread. Static setup does not measure its control word or prove OS FPU inheritance. A C bridge using integer floor(105*n/1000) is exact for the checked 53-bit multiply premise;64-bit alternative needs a separate worker control word premise. Period 0 remains special 1.

129A would produce 500 under either model in the default delay handler, but key/cancel/notification services do not take that handler.

SetWait throttle is separate:countdown chunks Sleep(min(remaining,100)); with SetWait(0), runner only calls Sleep(0) periodically on modulo 100 loop. Neither Sleep 15/30 passes nor period conversion establishes physical clock timing. Static GetTickCount/QueryPerformanceCounter calls belong to runtime cookie startup, not these handlers; timeGetTime is not imported.

## Other reasons and F000 observer

Reason 0 means no callback. Engine 100076B9..100076BD produces reason 1 from F009 bit 0. Reason 3 comes from unsupported/default opcode 1000724F; it was not identified as BRK. DLL 10005A65..10005A6D synthesizes reason 4 when execute returns nonzero while core reason is 0.

No audited native special callback on F000 writes exists. EXEdispatch reads 8E00; ordinary memory write 100032D0..100032EC → 10007A20..10007A3F has no F000 special case. Firmware reset 6FDE writes F000=0. Repository [test harness](../../../tools/nxu8/harness.c) and [platform adapter](../../../csrc/platform/fx_platform.c) deliberately observe nonzero F000 as callback_pending. That is a separate test/platform convention, not original Windows reason 2 callback behavior.

This audit supports software event ordering, queue consumption, completion bytes/bits and literal Sleep argument conversion. It does not establish measured Windows runtime, physical timing, GUI pixels, complete CPU interrupt parity or a firmware-understanding increment. Maintained [host bridge](../../../csrc/platform/fx_host_bridge.c) should preserve the stated distinction. Focused local disassembly and delay model are listed in [PROVENANCE.md](PROVENANCE.md).
