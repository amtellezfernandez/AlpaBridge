# Found while testing: utils_rs float encoder mishandles negative zero

**Status:** noted for later, not drafted as a PR/issue yet. Found incidentally while running `alpasim`'s own test suites end-to-end on real ARM64 hardware to verify the arm64-docker-build proposal - unrelated to that proposal itself.

## What's wrong

`src/utils_rs/src/grpc_boundary.rs`, `put_float_field`:

```rust
fn put_float_field(buf: &mut Vec<u8>, field_number: u32, value: f32) {
    if value.to_bits() == 0 { return; }
    ...
}
```

This skips writing a field when it's the proto3 default (`0.0`), but checks the raw bit pattern rather than numeric value. `(-0.0f32).to_bits()` is `0x80000000` (sign bit set), not `0`, so a `-0.0` value is treated as non-default and gets written explicitly. Google's protobuf (and this repo's own generated Python bindings) use numeric equality, where `-0.0 == 0.0` is `true`, so they correctly omit it.

Caught this because `src/utils/tests/test_grpc_boundary_rs.py::test_build_drive_response_bytes_matches_generated_proto_serialization` fails - its fixture happens to include a `-0.0` x-coordinate, and the Rust-built bytes end up 5 bytes longer than the Python-generated reference (one extra explicit field).

## Why this isn't part of the arm64-docker-build proposal

Pure integer bit-pattern comparison in Rust - architecture-independent, would fail identically on x86. Nothing to do with Docker, ARM64, or anything else in that proposal. Confirmed by reading the code, not by actually running on x86 (wasn't necessary - the logic itself doesn't reference any platform-specific behavior).

## Fix, verified

Changed the check from bit-pattern to numeric equality: `if value == 0.0 { return; }`.

Checked the NaN case explicitly rather than assuming: in both Rust and Python, `NaN == 0.0` is `false` (NaN compares unequal to everything, including itself), so a `NaN` field is written either way - this fix only changes behavior for `-0.0`, which now matches Python's `-0.0 == 0.0 → true` (omitted), same as before for every other value.

Actually rebuilt `utils_rs` with this change (`maturin develop --release`) and reran the real test suites against the built ARM64 image:
- `test_grpc_boundary_rs.py` - all 5 tests pass now (previously 1 failing).
- Full `src/utils` suite - 259 passed, 0 failed, 0 regressions.

Not committed anywhere - this was tested against a throwaway local checkout (off `main`, not the arm64-docker-build PR branch) purely to confirm the fix is real and correct before writing it down. Ready to turn into its own PR whenever that's next.
