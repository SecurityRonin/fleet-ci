pub fn a(x: u8) -> u8 {
    if x == 0 {
        // cov:unreachable: callers reject zero upstream, and the parser rejects
        // it again before this point, so this arm is dead under both. Kept so a
        // future caller that skips validation degrades instead of panicking.
        return 0;
    }
    x
}

pub fn b(x: u8) -> u8 {
    // cov:unreachable: this justification is separated from the uncovered line
    // by real code below, so it annotates something else entirely.
    let y = x.wrapping_add(1);
    if y == 0 {
        return 7;
    }
    y
}
