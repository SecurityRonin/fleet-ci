pub fn covered_fn(a: u8) -> u8 {
    a.wrapping_add(1)
}

pub fn uncovered_fn(a: u8) -> u8 {
    a.wrapping_sub(1)
}

pub fn guarded(a: u8) -> u8 {
    if a == 0 {
        return 0; // cov:unreachable: callers reject zero upstream
    }
    a
}
