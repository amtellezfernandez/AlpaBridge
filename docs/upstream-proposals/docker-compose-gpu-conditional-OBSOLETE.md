# Investigated: docker_compose.py GPU-conditional fix - already resolved upstream, no PR needed

**Status:** investigated, found moot. Not a proposal - documenting the finding so it isn't re-investigated later.

## What we thought we might propose

Our own `local_checkout.patch` (written against `v2026.5`) makes the runtime container's GPU device reservation conditional on whether any sim container actually declares a GPU (`if any(container.gpu is not None for container in container_set.sim or []): ret["deploy"] = {...}`), instead of unconditionally reserving `"count": "all"` GPUs for every runtime container regardless of whether anything needs one.

## What we found

Current `main`'s `docker_compose.py` has been substantially redesigned since `v2026.5` - the whole GPU-reservation section is different code now:

```python
if container.gpu is not None:
    ret["deploy"] = {
        "resources": {
            "reservations": {
                "devices": [
                    {
                        "driver": "nvidia",
                        "capabilities": ["gpu"],
                        "device_ids": [str(container.gpu)],
                    }
                ]
            }
        }
    }
elif container.name == "prometheus" and self.context.num_gpus > 0:
    ret["deploy"] = {
        "resources": {
            "reservations": {
                "devices": [
                    {
                        "driver": "nvidia",
                        "count": "all",
                        "capabilities": ["gpu"],
                    }
                ]
            }
        }
    }
```

This is a more thorough fix than what we were about to propose: reservation is now per-container (`container.gpu is not None`), assigning specific `device_ids` rather than blanket `"all"`, plus a separate, also-conditional (`num_gpus > 0`) case for prometheus. The one remaining `"count": "all"` in the file is that prometheus branch, which is already gated on `num_gpus > 0` - not the unconditional case our patch was written against.

The container-set structure has also changed (`container_set.runtime` is now a single optional container, not a list iterated with `for c in container_set.runtime or []`), so our old patch's context wouldn't even apply cleanly here regardless.

## Conclusion

No PR to prepare. The underlying problem (reserving GPUs even when nothing needs one) is already solved, more granularly than our proposal would have been. Not proposing anything here to avoid submitting a redundant/conflicting change against code that's moved on.
