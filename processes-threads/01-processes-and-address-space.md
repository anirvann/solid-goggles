# Processes & Address Space — Detailed Notes

> Companion deep-dive for the summary diagram: `processes-address-space-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand what a Linux process is, which resources it owns, how its virtual address space works, and what `fork()` actually copies (spoiler: mostly metadata + COW pages, not a full memory clone).

---

## 1) Big picture — what is a process?

A **process** is an isolated program-in-execution: its own virtual address space, credentials, open files, and (at least) one thread of control. On Linux the kernel does **not** have a separate “process object” vs “thread object.” Everything schedulable is a **`task_struct`** (a *task*). What userspace calls a “process” is really a **thread group**: one or more tasks that share a TGID (thread-group ID), which `getpid()` returns.

```
Userspace view:          Kernel view:
  Process P                thread group (tgid = P)
   ├─ main thread          ├─ task_struct (tid = P)
   ├─ worker A             ├─ task_struct (tid = A)
   └─ worker B             └─ task_struct (tid = B)
```

**Where it fits:** process isolation is the foundation for security (crash in one process doesn’t corrupt another’s memory), resource accounting (`setrlimit`, cgroups), and spawning workers (`fork`/`exec`, containers via namespaces).

---

## 2) What resources does a process own?

| Resource | Kernel structure | Role |
| --- | --- | --- |
| **Virtual memory** | `mm_struct` + page tables + VMAs | Private address space (code, heap, stack, mmap) |
| **File descriptors** | `files_struct` → fd table | Open files, sockets, pipes |
| **Filesystem context** | `fs_struct` | CWD, root, umask |
| **Signal handlers** | `sighand_struct` | How signals are handled |
| **Credentials** | `cred` | UID/GID, capabilities |
| **Namespaces** | mount/pid/net/user/… | Container isolation boundaries |
| **CPU scheduling state** | fields inside `task_struct` | Priority, vruntime, CPU affinity |
| **Resource limits** | `signal->rlim` / cgroups | Memory, FD count, CPU, etc. |

A process also has **identity**: PID (TGID), PPID, process group, session, controlling terminal.

---

## 3) Virtual address space (the process’s “private RAM map”)

Each process sees a huge linear address range (e.g. 128 TiB user space on x86-64). The MMU translates virtual → physical using **page tables**. The layout is typically:

```
high addresses
┌─────────────────────┐
│ kernel (not mapped  │  ← user code cannot touch
│  into user pages)   │
├─────────────────────┤
│ stack (grows ↓)     │  ← per-thread stacks live here too
├─────────────────────┤
│ mmap / shared libs  │
├─────────────────────┤
│ heap (grows ↑)      │  ← brk / malloc
├─────────────────────┤
│ BSS / data / text   │  ← globals + code
└─────────────────────┘
low addresses
```

**Key idea:** two processes can both have a pointer `0x7fff…` that means *completely different* physical memory. That isolation is why a wild write in process A cannot smash process B’s heap — the page tables differ.

**Shared memory exception:** `mmap(MAP_SHARED)`, System V `shm`, or POSIX shared memory can intentionally map the *same* physical pages into two processes.

---

## 4) Creating a process: `fork` / `clone` / `exec`

Linux unifies creation in **`clone` / `kernel_clone`**:

| Call | Typical effect |
| --- | --- |
| `fork()` | New task, **separate** address space (COW), copied FD table, new TGID |
| `vfork()` | Shares address space until `exec`/`_exit` (parent blocked) |
| `pthread_create()` | `clone` with `CLONE_VM\|FILES\|FS\|…` → **thread** |
| `execve()` | Replace address space with a new program image |

### Copy-on-Write (COW) — lucid example

```
Parent has page P with value "hello"
fork() →
  Parent PTE ──┐
               ├──► same physical frame (read-only)
  Child  PTE ──┘

Parent writes "HELLO" → page fault →
  Kernel allocates new frame, copies page, makes parent writable
  Child still sees "hello" on the old frame
```

So `fork()` is cheap until someone writes. `fork()` + immediate `exec()` is the classic spawn pattern: almost no COW copies happen because `exec` discards the address space.

**Hands-on:**

```bash
# See PIDs / TGIDs
ps -eLf | head
cat /proc/self/status | egrep '^(Name|Pid|Tgid|NSpid)'

# Address-space maps
cat /proc/self/maps | head
```

---

## 5) End-to-end flow — spawn a worker

```
1. Parent calls fork()
2. Kernel allocates new task_struct
3. Dup mm_struct + page tables (PTEs → shared COW pages)
4. Dup files_struct (FD table copy; open file descriptions shared)
5. Child returns 0; parent returns child PID
6. Child often calls execve("worker") → new mm, loads ELF
7. Scheduler runs both independently
```

| Step | Action | Risk |
| --- | --- | --- |
| fork | Duplicate task + mm metadata | Under memory pressure → `ENOMEM` |
| COW fault later | Real page copy on write | Latency spike / OOM |
| exec | Replace image | Wrong PATH / missing binary |
| wait | Reap child | Forget → zombie |

---

## 6) Reliability / security / ops lens

- **Isolation:** separate `mm` = memory safety boundary between apps.
- **Zombies:** unreaped children keep a `task_struct`; always `wait`/`waitpid` or use `SIGCHLD` handler / `PR_SET_CHILD_SUBREAPER`.
- **Fork bombs:** `RLIMIT_NPROC`, cgroup `pids.max`, `/proc/sys/kernel/pid_max`.
- **Credentials:** after `fork`, child inherits UID/caps — drop privileges before `exec` when sandboxed.
- **Observability:** `ps`, `/proc/<pid>/`, `pidstat`, cgroup memory/CPU controllers.

---

## 7) Key takeaways

- On Linux, a process is a **thread group** of `task_struct`s; isolation comes from what is *not* shared.
- The process’s private world is mainly its **`mm_struct` (address space)** plus FD/FS/signal/credential state.
- `fork()` does **not** eagerly copy all RAM — it uses **copy-on-write**.
- Use `fork`+`exec` (or `posix_spawn`) for new programs; use threads when you want shared memory by design.

---

## 8) Quick glossary

- **`task_struct`:** kernel object for one schedulable task (thread or single-threaded process).
- **`mm_struct`:** memory descriptor — virtual address space of a process.
- **TGID / TID:** thread-group ID (`getpid`) vs thread ID (`gettid`).
- **COW:** share physical pages read-only until a write forces a private copy.
- **VMA:** virtual memory area — a contiguous mapped range (`/proc/pid/maps` rows).

---

## Sources & further reading

- [clone(2) — Linux man-pages](https://man7.org/linux/man-pages/man2/clone.2.html)
- [fork(2) — Linux man-pages](https://man7.org/linux/man-pages/man2/fork.2.html)
- [What happens when you fork — Linux Kernel Internals](https://kernel-internals.org/mm/fork/)
- [Copy-on-Write — Linux Kernel Internals](https://kernel-internals.org/mm/cow/)
- [Launching Linux threads and processes with clone — Eli Bendersky](https://eli.thegreenplace.net/2018/launching-linux-threads-and-processes-with-clone)
- [Linux Process Management — task_struct, fork/clone/exec](https://systeminternals.dev/linux/process-management/)
