.PHONY: paper test clean

paper:
	$(MAKE) -C paper

test:
	pytest tests/test_alpasim_integration.py \
		tests/test_alpasim_setup_scripts.py \
		tests/test_check_alpasim_readiness.py \
		tests/test_run_alpasim_scene_batch.py \
		tests/test_audit_alpasignal_bridge.py

clean:
	$(MAKE) -C paper clean
