# Proposed upstream PR: fix utils_rs dropping -0.0 as if it were the proto3 default

**Status:** drafted and verified against `NVlabs/alpasim` `main` (commit `3032e0c`), not yet opened.

## Why

`src/utils_rs/src/grpc_boundary.rs`, `put_float_field`:

```rust
fn put_float_field(buf: &mut Vec<u8>, field_number: u32, value: f32) {
    if value.to_bits() == 0 {
        return;
    }
    put_key(buf, field_number, WIRE_FIXED32);
    buf.extend_from_slice(&value.to_le_bytes());
}
```

This skips writing a field when it's the proto3 default (`0.0`), but checks the raw bit pattern rather than numeric value. `(-0.0f32).to_bits()` is `0x80000000` (sign bit set), not `0`, so a `-0.0` value is treated as non-default and gets written explicitly. Google's protobuf - and this repo's own generated Python bindings - use numeric equality, where `-0.0 == 0.0` is `true`, so they correctly omit it. The Rust-encoded bytes and the Python-encoded bytes for the same logical message diverge whenever a `-0.0` coordinate is involved.

Found this via `src/utils/tests/test_grpc_boundary_rs.py::test_build_drive_response_bytes_matches_generated_proto_serialization`: its fixture happens to include a `-0.0` x-coordinate, and the Rust-built bytes end up 5 bytes longer than the Python-generated reference (one extra explicit field).

This is pure integer bit-pattern comparison in Rust - architecture-independent, would fail identically on x86. Unrelated to the [arm64-docker-build proposal](./arm64-docker-build.md); found incidentally while running AlpaSim's own test suites end-to-end on real ARM64 hardware to verify that one.

## The change

Switch the check from bit-pattern to numeric equality.

```diff
diff --git a/src/utils_rs/src/grpc_boundary.rs b/src/utils_rs/src/grpc_boundary.rs
--- a/src/utils_rs/src/grpc_boundary.rs
+++ b/src/utils_rs/src/grpc_boundary.rs
@@ -190,7 +190,7 @@ fn encode_pose(xyz: &[f32], quat_wxyz: &[f32]) -> Vec<u8> {
 }
 
 fn put_float_field(buf: &mut Vec<u8>, field_number: u32, value: f32) {
-    if value.to_bits() == 0 {
+    if value == 0.0 {
         return;
     }
     put_key(buf, field_number, WIRE_FIXED32);
```

`NaN` is unaffected: `NaN == 0.0` is `false` in both Rust and Python (`NaN` compares unequal to everything, including itself), so a `NaN` field is still written either way - this only changes behavior for `-0.0`, which now matches Python's `-0.0 == 0.0 → true` (omitted), same as before for every other value.

## Verification performed

- `git apply --check` / `git am` clean against a fresh clone of `main` (commit `3032e0c`).
- Isolated the exact `to_bits() == 0` vs `value == 0.0` comparison in a standalone Rust program (`rustc -O`, no crate build needed since the logic doesn't touch any `pyo3`/`numpy`/`glam` dependency) and enumerated `0.0`, `-0.0`, `1.0`, `-1.0`, `NaN`, `inf`: only `-0.0` changes from "written" to "omitted"; every other case, including `NaN`, is unchanged.
- Previously (see git history of this note): rebuilt the real `utils_rs` extension with this change (`maturin develop --release`) and reran the actual test suites against a built ARM64 image - `test_grpc_boundary_rs.py` went from 1 failing to all 5 passing, and the full `src/utils` suite (259 tests) had 0 regressions. That build was against a throwaway local checkout, not committed anywhere at the time.

## How to open this, once approved

```bash
cd <clone of amtellezfernandez/alpasim tracking upstream main>
git checkout -b fix/utils-rs-negative-zero
git am third_party/alpasim_overrides/utils-rs-negative-zero-serialization.patch  # patch is git-am-ready, own Subject/body
git push fork fix/utils-rs-negative-zero
gh pr create --repo NVlabs/alpasim --base main \
  --head amtellezfernandez:fix/utils-rs-negative-zero \
  --title "utils_rs: fix put_float_field dropping -0.0 as if non-default" \
  --body-file <PR description derived from the "Why" section above>
```
