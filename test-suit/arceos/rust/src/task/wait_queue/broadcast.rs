//! A notification may select each registration in its initial cohort once.

use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    thread,
    vec::Vec,
};

use ax_std::os::arceos::{
    api::task::{self as api, AxWaitQueueHandle},
    task::{
        sched::{CpuId, CpuSet, RtPriority, SchedulePolicy},
        thread::current::current_thread_handle,
    },
};

pub(super) fn run() {
    let controller = current_thread_handle().expect("wait-queue controller");
    let original_affinity = controller.affinity().expect("controller affinity");
    let mut affinity = CpuSet::empty(ax_std::os::arceos::task::sched::cpu_topology_len().unwrap());
    assert!(affinity.insert(CpuId::new(0)));
    controller
        .set_affinity_and_wait(affinity.clone())
        .expect("pin notification controller");
    let mut delivered = Vec::new();
    for requested in [2, u32::MAX] {
        let queue = Arc::new(AxWaitQueueHandle::new());
        let checks = Arc::new(AtomicUsize::new(0));
        let stop = Arc::new(AtomicBool::new(false));
        let worker_queue = queue.clone();
        let worker_checks = checks.clone();
        let worker_stop = stop.clone();
        let worker = ax_std::os::arceos::thread::builder("broadcast-rewaiter".into())
            .policy(SchedulePolicy::fifo(RtPriority::new(80).unwrap()))
            .affinity(affinity.clone())
            .spawn(move || {
                // The finite escape makes a broken reselecting broadcast return
                // an excessive count instead of permanently hanging the suite.
                api::ax_wait_queue_wait_until(
                    &worker_queue,
                    || {
                        worker_stop.load(Ordering::Acquire)
                            || worker_checks.fetch_add(1, Ordering::AcqRel) >= 7
                    },
                    None,
                );
            })
            .expect("spawn FIFO condition waiter");
        // Both tasks are on CPU0. Once the FIFO task ran its first predicate,
        // this normal-policy controller cannot resume until that task blocks.
        while checks.load(Ordering::Acquire) == 0 {
            thread::yield_now();
        }
        let count = api::ax_wait_queue_wake(&queue, requested);
        stop.store(true, Ordering::Release);
        api::ax_wait_queue_wake(&queue, 1);
        worker.join().expect("join requeued waiter");
        println!(
            "task_wait_queue: cohort requested={requested} delivered={count} checks={}",
            checks.load(Ordering::Acquire)
        );
        delivered.push(count);
    }
    controller
        .set_affinity_and_wait(original_affinity)
        .expect("restore controller affinity");
    assert_eq!(
        delivered,
        [1, 1],
        "one notification repeatedly selected a requeued waiter"
    );
    println!("task_wait_queue: notification cohort OK");
}
