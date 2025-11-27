.PHONY: install
install:
	@echo "Clearing local environment"
	@rm -rf ./env
	@echo "Creating virtual environment"
	@python -m venv env
	@echo "Activating virtual environment"
	@. env/bin/activate
	@echo "Installing packages"
	@pip install -e .

.PHONY: run
run:
	@echo "Activating virtual environment"
	@. env/bin/activate
	@echo "Running the application via Uvicorn"
	uvicorn fip_version_project_action:create_app --reload --proxy-headers --forwarded-allow-ips=* --host 0.0.0.0 --port 8000
