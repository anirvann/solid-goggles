# Threads & Resource Sharing — Detailed Notes

> Companion deep-dive for the summary diagram: `threads-resource-sharing-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** See how Linux threads are just tasks that **share** selected resources (especially memory and FDs), what stays private per thread, and why that sharing enables fast concurrency — and race conditions.

---

## 1) Big picture — threads are sharing tasks

Popular myth: “the kernel has Processes and Threads as two types.”  
Linux truth: **only tasks**. A **thread** is a task created with `clone()` flags that share the parent’s resources — most importantly **`CLONE_VM`** (same address space).

```c
/* Conceptual pthread_create → clone flags */
clone(CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND |
      CLONE_THREAD | CLONE_SYSVSEM | CLONE_SETTLS | …);
```

| Abstraction | Sharing? |
| --- | --- |
| Two processes (`fork`) | Separate mm, separate FD tables (copied), separate TGIDs |
| Two threads (`pthread_create`) | **Same** mm, **same** FD table, **same** TGID |

---

## 2) Memory sharing — lucid example

```c
#include <pthread.h>
#include <stdio.h>

int shared = 0;           /* data segment — SHARED by all threads */

void *worker(void *arg) {
    int local = 1;        /* stack — PRIVATE to this thread */
    shared += 1;          /* visible to every thread in the process */
    printf("tid local=%d shared=%d\n", local, shared);
    return NULL;
}

int main(void) {
    pthread_t t1, t2;
    pthread_create(&t1, NULL, worker, NULL);
    pthread_create(&t2, NULL, worker, NULL);
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    printf("final shared=%d\n", shared);  /* expect 2 (if no races on print) */
}
```

**What is shared in memory:**

| Region | Shared across threads? | Notes |
| --- | --- | --- |
| Code (text) | Yes | Same instructions |
| Globals / statics | Yes | Instant visibility |
| Heap (`malloc`) | Yes | One heap; need locks/`malloc` is thread-safe but your data isn’t automatically |
| Memory-mapped files | Yes | Same mappings |
| Thread stack | **No** | Each thread has its own stack + stack pointer |
| Registers / PC | **No** | Each task has its own CPU context |
| Thread-local storage (TLS) | **No** | `__thread` / `thread_local` per thread |

**Mental model:** threads = multiple CPUs walking around the **same house** (address space). Processes = separate houses (with optional shared garage via `mmap` shared).

---

## 3) Resource sharing — *what* resources?

POSIX requires many attributes to be **process-wide** (shared by all threads). From `pthreads(7)`:

### Shared (process-wide)

| Resource | Why it matters |
| --- | --- |
| **Process ID (TGID)** | `getpid()` same in all threads |
| **Open file descriptors** | `close(fd)` in one thread closes it for all |
| **File offset** of an open file description | Concurrent `read`/`write` without care → interleaved data |
| **Current working directory / root / umask** | `chdir` affects every thread |
| **Signal dispositions** | One handler table for the process |
| **User/group IDs, nice, rlimits** | Process-scoped accounting |
| **Record locks (`fcntl`)** | Process-wide |
| **Interval / POSIX timers** | Process-wide |
| **SysV semaphores undo** (with `CLONE_SYSVSEM`) | Shared undo list |

### Private (per-thread)

| Resource | Why it matters |
| --- | --- |
| **Thread ID (TID / `pthread_t`)** | Identify the task |
| **Stack + registers** | Independent call chains |
| **Signal mask** | Block signals per thread |
| **`errno`** | Thread-local in modern libc |
| **Scheduling policy/priority** (often) | Can differ per thread |
| **CPU affinity** (Linux) | Pin workers to cores |
| **Alternate signal stack** | Per-thread |
| **TLS / capabilities (Linux)** | Per-thread state |

### `clone` flags → sharing knobs

| Flag | Shares |
| --- | --- |
| `CLONE_VM` | Address space (`mm_struct`) — *defines “thread-like”* |
| `CLONE_FILES` | FD table |
| `CLONE_FS` | CWD / root / umask |
| `CLONE_SIGHAND` | Signal handlers |
| `CLONE_THREAD` | Same thread group (same TGID, shared process signals) |
| `CLONE_SETTLS` | Set up TLS for new thread |

---

## 4) End-to-end flow — create a worker thread

```
App                        Kernel
 │  pthread_create()
 ├──────────────────────►  clone(CLONE_VM|FILES|…)
 │                         allocate task_struct
 │                         share mm_struct (refcount++)
 │                         share files_struct
 │                         new kernel stack + user stack
 │                         set TLS
 │  ◄────────────────────  new TID runnable
 │
 │  both threads run; scheduler may interleave on 1 core
 │  or run truly parallel on N cores
 │
 │  pthread_join()  ─────► wait until worker exits
```

| Step | Decision | Risk |
| --- | --- | --- |
| Share heap | Need mutex/atomics? | Data races / torn reads |
| Share FD | Who closes sockets? | Use-after-close |
| Exit process | `exit()` kills **all** threads | Prefer return from main + joins, or `_exit` carefully |
| Fork from multi-threaded process | Only forking thread survives in child | Async-signal-safe only between fork and exec |

---

## 5) Concurrency consequences (why sharing hurts if careless)

**Lucid race:**

```c
// BAD: two threads do balance += 100 without a lock
// Both read 1000, both write 1100 → lost update (expected 1200)
```

**Fixes:** mutexes, atomics, lock-free structures, or **don’t share** — use message passing / one thread owns the data.

**Deadlock sketch:** Thread A locks M1 waits M2; Thread B locks M2 waits M1.

---

## 6) Reliability / security / ops

- Prefer **bounded thread pools** over unbounded `pthread_create` per request (stack memory + scheduler load).
- Stack size defaults (~8 MiB virtual on Linux) × thread count = huge virtual size; watch `ulimit -s` and `pthread_attr_setstacksize`.
- Signal handling in multi-threaded apps: usually dedicate one thread with `sigwait`, keep others blocked.
- After `fork` in a multi-threaded program, only async-signal-safe calls until `exec` — locks held by other (now dead) threads stay locked forever in the child.
- Observe: `ps -eLf`, `top -H`, `/proc/<pid>/task/`, `perf top`.

---

## 7) Key takeaways

- Threads = tasks that **share an address space** (`CLONE_VM`) and usually FDs/FS/signals.
- **Shared:** heap, globals, FDs, CWD, signal dispositions, PID.
- **Private:** stack, registers, signal mask, errno, TLS, TID.
- Sharing is the feature (cheap communication) and the hazard (races, lock bugs).
- Processes isolate by default; threads share by default — pick based on fault isolation vs latency.

---

## 8) Quick glossary

- **Thread group:** set of tasks with the same TGID (a “process” in POSIX terms).
- **TLS:** thread-local storage — variables private to one thread.
- **Data race:** conflicting concurrent access to shared memory without synchronization.
- **NPTL:** Native POSIX Thread Library — Linux’s modern pthread implementation via `clone`.
- **Green threads / userspace threads:** scheduled in userspace (e.g. goroutines M:N); still backed by OS threads underneath.

---

## Sources & further reading

- [pthreads(7) — Linux man-pages](https://man7.org/linux/man-pages/man7/pthreads.7.html) — authoritative shared vs per-thread attribute list
- [clone(2) — Linux man-pages](https://man7.org/linux/man-pages/man2/clone.2.html)
- [Launching Linux threads and processes with clone — Eli Bendersky](https://eli.thegreenplace.net/2018/launching-linux-threads-and-processes-with-clone)
- [The Linux Implementation of Threads — Linux Kernel Development (excerpt)](https://litux.nl/mirror/kerneldevelopment/0672327201/ch03lev1sec3.html)
- [CS3130: Processes and threads — University of Virginia](https://www.cs.virginia.edu/~cr4bd/3130/F2025/readings/thread.html)
