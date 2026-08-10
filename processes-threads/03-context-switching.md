# Context Switching — Detailed Notes

> Companion deep-dive for the summary diagram: `context-switching-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand what a context switch is, **what state is saved/restored**, why switching between threads of the same process is cheaper than switching processes, and how excessive switching (e.g. too many DB connections) burns CPU.

---

## 1) Big picture — what is a context switch?

A **context switch** is the kernel pausing one task and resuming another on a CPU core. The CPU can only execute one thread’s user instructions per core at a time; multitasking is an illusion built by rapid switching (plus true parallelism across cores).

**Triggers:**

| Trigger | Example |
| --- | --- |
| **Blocking** | `read()` waits on disk/network; mutex wait; `sleep` |
| **Preemption** | Time slice / timer tick; higher-priority task woke up |
| **Voluntary yield** | `sched_yield()`, finishing work and parking |

On Linux the scheduler (historically **CFS**, evolving toward **EEVDF**) picks the next runnable task; then architecture code performs the actual switch (`__switch_to` / `__switch_to_asm` on x86).

---

## 2) What is “context”? — what gets saved

Think of context as **everything needed to resume exactly where you left off**.

### Always switched (every task → task)

| State | Where kept | Notes |
| --- | --- | --- |
| **General-purpose registers** | On kernel stack / `thread_struct` | IP/PC, SP, callee-saved regs |
| **Kernel stack pointer** | `task→thread.sp` | Core of the switch: swap stacks |
| **CPU flags** | Saved/restored as needed | e.g. RFLAGS |
| **FPU / SIMD** | Lazy or eager save | AVX state is large — costly if hot |
| **TLS / FS-GS base** | Per-thread | Thread-local access |
| **Scheduler metadata** | `task_struct` | Not “CPU regs” but accounting |

### Extra cost when switching **processes** (different `mm_struct`)

| State | Cost |
| --- | --- |
| **CR3 / page-table root** | Must load new address space |
| **TLB (translation cache)** | Often flushed or tagged (ASID/PCID); misses follow |
| **Cache warmth** | New process touches different memory → cold caches |

**Lucid analogy:**

- **Thread switch (same process):** change which person is typing on the **same desk** (same papers = same memory). Swap notepad (registers/stack). Desk stays.
- **Process switch:** wheel in a **whole different desk** (new page tables). You also forget where things were (TLB/cache).

That is why thread switches are typically cheaper than process switches.

---

## 3) End-to-end flow — one switch on x86-64 (simplified)

```
Task A running in userspace
        │
        ▼  (timer IRQ / syscall that blocks / wake of higher prio)
Enter kernel (save user regs on A’s kernel stack)
        │
        ▼
schedule() → pick_next_task() → choose Task B
        │
        ▼
context_switch(A, B):
  1. If A->mm != B->mm → switch_mm() (load B’s CR3)
  2. switch_to(A, B):
       save A’s callee-saved regs
       store CPU %rsp into A->thread.sp
       load B->thread.sp into %rsp      ← now on B’s kernel stack
       restore B’s regs
        │
        ▼
Return to userspace as Task B (as if B never stopped)
```

The heart is often described as **two instructions**: save old RSP, load new RSP — because the rest of B’s state lives on B’s stack.

---

## 4) Context sharing vs context switching

| Term | Meaning |
| --- | --- |
| **Context sharing** | Threads in one process **share** address space & many kernel resources — they do *not* each need a full mm switch when alternating |
| **Context switching** | Saving/restoring **CPU execution state** so another task can run |

Threads still **context-switch** (registers + stack). They often **skip the address-space switch**. Processes do both.

```
Same-process thread A → thread B:
  ✓ save/restore registers & stack
  ✗ no CR3 change (same mm)
  ✗ TLB mostly preserved

Process P1 → process P2:
  ✓ registers & stack
  ✓ CR3 / mm switch
  ✓ TLB disruption + colder caches
```

---

## 5) Cost and why it shows up in connection pools

Context switches aren’t free:

1. Direct CPU time saving/restoring state  
2. Pipeline flush  
3. TLB / cache pollution  
4. Lock contention amplification when too many tasks fight  

**PostgreSQL lesson (process-per-connection):** each client connection ≈ a backend **process**. Too many connections → too many processes runnable → **context-switch storm** + lock/cache-line contention → throughput *falls* after a “knee.” Connection pooling exists partly to **cap runnable processes** and cut switching.

**Rule of thumb from PG wiki:** active connections near `((cores × 2) + spindles)` — beyond saturation, queue work instead of adding runners.

**Observe switches:**

```bash
# system-wide context switches / sec
vmstat 1
# per-process
pidstat -w 1
# voluntary vs involuntary
cat /proc/<pid>/status | egrep '^(voluntary|nonvoluntary)_ctxt_switches'
```

---

## 6) Reliability / security / ops

- **Too many threads/processes:** latency spikes, CPU in `%system`, high `cs` in `vmstat`.
- **Priority inversion / noisy neighbors:** cgroups + CPU shares; realtime policies carefully.
- **Kernel bypass / busy-poll:** reduce switches for ultra-low latency (DPDK, etc.) — specialized.
- **Security:** spectre/meltdown mitigations made some switches slightly more expensive (RSB fill, etc.) — still mandatory.
- **Tuning:** fewer, busier workers often beat many idle ones; pair with pools and queues.

---

## 7) Key takeaways

- A context switch saves one task’s **CPU execution state** and loads another’s.
- **Thread switch** ≈ registers/stack; **process switch** ≈ that **plus** address space (CR3/TLB).
- Threads **share** memory context; they still **switch** CPU context.
- Excess parallelism → excess switching → less useful work (classic DB connection knee).
- Measure with `vmstat` / `pidstat -w` before guessing.

---

## 8) Quick glossary

- **PCB / `task_struct`:** process/task control block holding scheduling + pointers to mm/files.
- **TLB:** cache of virtual→physical translations; sensitive to mm switches.
- **Preemption:** kernel forcibly switches out a still-runnable task.
- **Voluntary vs involuntary switch:** blocked vs preempted (`/proc/pid/status`).
- **Runqueue:** per-CPU structure of runnable tasks the scheduler picks from.

---

## Sources & further reading

- [Context switch — Wikipedia](https://en.wikipedia.org/wiki/Context_switch) (overview of PCB / TLB effects)
- [Evolution of the x86 context switch in Linux — MaiZure](https://www.maizure.org/projects/evolution_x86_context_switch_linux/)
- [CFS Scheduler — The Linux Kernel docs](https://kernel.org/doc/html/latest/scheduler/sched-design-CFS.html)
- [Number Of Database Connections — PostgreSQL Wiki](https://wiki.postgresql.org/wiki/Number_Of_Database_Connections) (context switches as a scaling cost)
- [arch/x86 entry / switch paths — Linux kernel source](https://github.com/torvalds/linux/tree/master/arch/x86)
