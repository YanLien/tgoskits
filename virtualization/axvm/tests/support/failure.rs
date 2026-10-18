//! Bounded committed-prefix diagnostics, only after all fixture VMs have joined.

use std::collections::{BTreeMap, VecDeque};

use axvm::diagnostics::{Event, EventKind};

const MAX_GROUPS: usize = 256;
const RECENT_PER_CPU: usize = 16;

pub(super) fn report_after_shutdown() {
    let snapshot = match axvm::diagnostics::finish() {
        Ok(snapshot) => snapshot,
        Err(error) => {
            println!("VIRQ_FAILURE_TRACE unavailable={error}");
            return;
        }
    };
    println!(
        "VIRQ_FAILURE_TRACE records={} dropped={} incomplete={} diagnostic_only=1 \
         scope=committed_prefix",
        snapshot.events.len(),
        snapshot.dropped,
        snapshot.incomplete
    );
    let mut groups = BTreeMap::new();
    let mut recent = BTreeMap::<usize, VecDeque<&Event>>::new();
    for event in &snapshot.events {
        let group = groups
            .entry((event.cpu, event.thread, event.kind as u64))
            .or_insert((event.kind, 0usize, event.ticks, event.ticks));
        group.1 += 1;
        group.3 = event.ticks;
        let tail = recent.entry(event.cpu).or_default();
        if tail.len() == RECENT_PER_CPU {
            tail.pop_front();
        }
        tail.push_back(event);
    }
    for ((cpu, thread, _), (kind, count, first, last)) in groups.iter().take(MAX_GROUPS) {
        println!(
            "VIRQ_FAILURE_KIND cpu={cpu} thread={thread} kind={kind:?} count={count} \
             first_ticks={first} last_ticks={last}"
        );
    }
    println!(
        "VIRQ_FAILURE_GROUPS total={} omitted={}",
        groups.len(),
        groups.len().saturating_sub(MAX_GROUPS)
    );
    let boundaries: Vec<_> = snapshot
        .events
        .iter()
        .filter(|event| matches!(event.kind, EventKind::Binding | EventKind::Marker))
        .collect();
    for event in boundaries.iter().take(MAX_GROUPS) {
        report_event("boundary", event);
    }
    println!(
        "VIRQ_FAILURE_BOUNDARIES total={} omitted={}",
        boundaries.len(),
        boundaries.len().saturating_sub(MAX_GROUPS)
    );
    for tail in recent.values() {
        for event in tail {
            report_event("tail", event);
        }
    }
}

fn report_event(scope: &str, event: &Event) {
    println!(
        "VIRQ_FAILURE_EVENT scope={scope} cpu={} sequence={} ticks={} kind={:?} thread={} \
         value0={} value1={}",
        event.cpu,
        event.sequence,
        event.ticks,
        event.kind,
        event.thread,
        event.value0,
        event.value1
    );
}
