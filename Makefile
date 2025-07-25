# Makefile for generating Python proto files from Cadence protobuf definitions

# Versioned protoc support
# https://www.grpc.io/docs/languages/go/quickstart/
# changing PROTOC_VERSION will automatically download and use the specified version
PROTOC_VERSION = 3.14.0
PROTOC_VERSION_PYI = 25.3

EMULATE_X86 =
ifeq ($(shell uname -sm),Darwin arm64)
EMULATE_X86 = arch -x86_64
endif

OS := $(shell uname -s)
ARCH := $(shell $(EMULATE_X86) uname -m)

PROTOC_URL = https://github.com/protocolbuffers/protobuf/releases/download/v$(PROTOC_VERSION)/protoc-$(PROTOC_VERSION)-$(subst Darwin,osx,$(OS))-$(ARCH).zip
PROTOC_URL_PYI = https://github.com/protocolbuffers/protobuf/releases/download/v$(PROTOC_VERSION_PYI)/protoc-$(PROTOC_VERSION_PYI)-$(subst Darwin,osx,$(OS))-$(ARCH).zip
# the zip contains an /include folder that we need to use to learn the well-known types
PROTOC_UNZIP_DIR = $(STABLE_BIN)/protoc-$(PROTOC_VERSION)-zip
PROTOC_UNZIP_DIR_PYI = $(STABLE_BIN)/protoc-$(PROTOC_VERSION_PYI)-zip
# use PROTOC_VERSION_BIN as a bin prerequisite, not "protoc", so the correct version will be used.
# otherwise this must be a .PHONY rule, or the buf bin / symlink could become out of date.
PROTOC_VERSION_BIN = protoc-$(PROTOC_VERSION)
PROTOC_VERSION_BIN_PYI = protoc-$(PROTOC_VERSION_PYI)

# Stable binary directory
STABLE_BIN := .bin

# Quiet mode support
Q := @

# Directories
SRC_DIR := idls/proto
DST_DIR := cadence/shared
TEMP_DIR := .temp_gen
PROTO_ROOT := $(SRC_DIR)/uber/cadence

# Find all .proto files
API_PROTO_FILES := $(wildcard $(PROTO_ROOT)/api/v1/*.proto)
ADMIN_PROTO_FILES := $(wildcard $(PROTO_ROOT)/admin/v1/*.proto)
ALL_PROTO_FILES := $(API_PROTO_FILES) $(ADMIN_PROTO_FILES)

# Python output files (replace .proto with _pb2.py)
API_PYTHON_FILES := $(patsubst $(PROTO_ROOT)/api/v1/%.proto,$(DST_DIR)/api/v1/%_pb2.py,$(API_PROTO_FILES))
ADMIN_PYTHON_FILES := $(patsubst $(PROTO_ROOT)/admin/v1/%.proto,$(DST_DIR)/admin/v1/%_pb2.py,$(ADMIN_PROTO_FILES))
ALL_PYTHON_FILES := $(API_PYTHON_FILES) $(ADMIN_PYTHON_FILES)

# Python interface files (replace .proto with _pb2.pyi)
API_PYI_FILES := $(patsubst $(PROTO_ROOT)/api/v1/%.proto,$(DST_DIR)/api/v1/%_pb2.pyi,$(API_PROTO_FILES))
ADMIN_PYI_FILES := $(patsubst $(PROTO_ROOT)/admin/v1/%.proto,$(DST_DIR)/admin/v1/%_pb2.pyi,$(ADMIN_PROTO_FILES))
ALL_PYI_FILES := $(API_PYI_FILES) $(ADMIN_PYI_FILES)

# All generated files
ALL_GENERATED_FILES := $(ALL_PYTHON_FILES) $(ALL_PYI_FILES)

# Default target
.PHONY: all
all: $(ALL_GENERATED_FILES)

# Parallel target - use with make -j
.PHONY: parallel
parallel: $(ALL_GENERATED_FILES)

# Create output directories
$(DST_DIR)/api/v1/:
	mkdir -p $(DST_DIR)/api/v1

$(DST_DIR)/admin/v1/:
	mkdir -p $(DST_DIR)/admin/v1

# Download and setup versioned protoc
$(STABLE_BIN)/$(PROTOC_VERSION_BIN): | $(STABLE_BIN)
	$(Q) echo "downloading protoc $(PROTOC_VERSION): $(PROTOC_URL)"
	$(Q) # recover from partial success
	$(Q) rm -rf $(STABLE_BIN)/protoc.zip $(PROTOC_UNZIP_DIR)
	$(Q) # download, unzip, copy to a normal location
	$(Q) curl -sSL $(PROTOC_URL) -o $(STABLE_BIN)/protoc.zip
	$(Q) unzip -q $(STABLE_BIN)/protoc.zip -d $(PROTOC_UNZIP_DIR)
	$(Q) cp $(PROTOC_UNZIP_DIR)/bin/protoc $@

# Download and setup versioned protoc for .pyi generation
$(STABLE_BIN)/$(PROTOC_VERSION_BIN_PYI): | $(STABLE_BIN)
	$(Q) echo "downloading protoc $(PROTOC_VERSION_PYI) for .pyi generation: $(PROTOC_URL_PYI)"
	$(Q) # recover from partial success
	$(Q) rm -rf $(STABLE_BIN)/protoc-pyi.zip $(PROTOC_UNZIP_DIR_PYI)
	$(Q) # download, unzip, copy to a normal location
	$(Q) curl -sSL $(PROTOC_URL_PYI) -o $(STABLE_BIN)/protoc-pyi.zip
	$(Q) unzip -q $(STABLE_BIN)/protoc-pyi.zip -d $(PROTOC_UNZIP_DIR_PYI)
	$(Q) cp $(PROTOC_UNZIP_DIR_PYI)/bin/protoc $@

# Create stable bin directory
$(STABLE_BIN):
	mkdir -p $(STABLE_BIN)

# Generate all Python files in a single protoc call
$(ALL_PYTHON_FILES): $(ALL_PROTO_FILES) | $(DST_DIR)/api/v1/ $(DST_DIR)/admin/v1/ $(STABLE_BIN)/$(PROTOC_VERSION_BIN)
	@echo "Generating all Python .py files from $(words $(ALL_PROTO_FILES)) proto files using protoc $(PROTOC_VERSION)"
	rm -rf $(TEMP_DIR)
	mkdir -p $(TEMP_DIR)
	cd $(SRC_DIR) && $(CURDIR)/$(STABLE_BIN)/$(PROTOC_VERSION_BIN) --proto_path=. --proto_path=$(CURDIR)/$(PROTOC_UNZIP_DIR)/include --python_out=$(CURDIR)/$(TEMP_DIR) $(patsubst $(SRC_DIR)/%,%,$(ALL_PROTO_FILES))
	mv $(TEMP_DIR)/uber/cadence/api/v1/*.py $(DST_DIR)/api/v1/
	mv $(TEMP_DIR)/uber/cadence/admin/v1/*.py $(DST_DIR)/admin/v1/
	rm -rf $(TEMP_DIR)

# Generate all Python interface files using newer protoc
$(ALL_PYI_FILES): $(ALL_PROTO_FILES) | $(DST_DIR)/api/v1/ $(DST_DIR)/admin/v1/ $(STABLE_BIN)/$(PROTOC_VERSION_BIN_PYI)
	@echo "Generating all Python .pyi files from $(words $(ALL_PROTO_FILES)) proto files using protoc $(PROTOC_VERSION_PYI)"
	rm -rf $(TEMP_DIR)-pyi
	mkdir -p $(TEMP_DIR)-pyi
	cd $(SRC_DIR) && $(CURDIR)/$(STABLE_BIN)/$(PROTOC_VERSION_BIN_PYI) --proto_path=. --proto_path=$(CURDIR)/$(PROTOC_UNZIP_DIR_PYI)/include --pyi_out=$(CURDIR)/$(TEMP_DIR)-pyi $(patsubst $(SRC_DIR)/%,%,$(ALL_PROTO_FILES))
	mv $(TEMP_DIR)-pyi/uber/cadence/api/v1/*.pyi $(DST_DIR)/api/v1/
	mv $(TEMP_DIR)-pyi/uber/cadence/admin/v1/*.pyi $(DST_DIR)/admin/v1/
	rm -rf $(TEMP_DIR)-pyi

# All generated files
ALL_GENERATED_FILES := $(ALL_PYTHON_FILES) $(ALL_PYI_FILES)

# Clean generated files
.PHONY: clean
clean:
	rm -rf $(DST_DIR)
	rm -rf $(TEMP_DIR)
	rm -rf $(TEMP_DIR)-pyi
	rm -rf $(STABLE_BIN)

# Show help
.PHONY: help
help:
	@echo "Available targets:"
	@echo "  all      - Generate all Python proto files (.py and .pyi) (default)"
	@echo "  parallel - Same as 'all' (single protoc call for all files)"
	@echo "  clean    - Remove all generated files and downloaded protoc"
	@echo "  help     - Show this help message"
	@echo "  show     - Show what files will be processed"
	@echo ""
	@echo "Features:"
	@echo "  - Uses protoc $(PROTOC_VERSION) for .py files (matches Cadence server)"
	@echo "  - Uses protoc $(PROTOC_VERSION_PYI) for .pyi files (modern .pyi support)"
	@echo "  - Automatically downloads protoc versions if not present"
	@echo "  - Single protoc call generates all files efficiently"
	@echo "  - Apple Silicon support via Rosetta emulation"
	@echo ""
	@echo "Generated files will be placed in:"
	@echo "  $(DST_DIR)/api/v1/  - API proto files (.py and .pyi)"
	@echo "  $(DST_DIR)/admin/v1/ - Admin proto files (.py and .pyi)"
	@echo "  $(STABLE_BIN)/      - Downloaded protoc binaries"

# Show what will be generated
.PHONY: show
show:
	$(info Proto files to process:)
	$(info API_PROTO_FILES: $(API_PROTO_FILES))
	$(info ADMIN_PROTO_FILES: $(ADMIN_PROTO_FILES))
	$(info )
	$(info Python files to generate:)
	$(info API_PYTHON_FILES: $(API_PYTHON_FILES))
	$(info ADMIN_PYTHON_FILES: $(ADMIN_PYTHON_FILES))
	$(info )
	$(info Python interface files to generate:)
	$(info API_PYI_FILES: $(API_PYI_FILES))
	$(info ADMIN_PYI_FILES: $(ADMIN_PYI_FILES)) 