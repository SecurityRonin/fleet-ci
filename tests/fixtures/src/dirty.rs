pub fn used(a: u8) -> u8 { a }
pub fn never_entered(a: u8) -> u8 { a }
pub fn dead_guard(a: u8) -> u8 { a } // cov:unreachable: unreachable in this build
