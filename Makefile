# Makefile for generating Python proto files from Cadence protobuf definitions

# Directories
SRC_DIR := idls/proto
DST_DIR := .gen
PROTO_ROOT := $(SRC_DIR)/uber/cadence

# Find all .proto files
API_PROTO_FILES := $(wildcard $(PROTO_ROOT)/api/v1/*.proto)
ADMIN_PROTO_FILES := $(wildcard $(PROTO_ROOT)/admin/v1/*.proto)
ALL_PROTO_FILES := $(API_PROTO_FILES) $(ADMIN_PROTO_FILES)

# Python output files (replace .proto with _pb2.py) - protoc preserves full path structure
API_PYTHON_FILES := $(patsubst $(PROTO_ROOT)/api/v1/%.proto,$(DST_DIR)/uber/cadence/api/v1/%_pb2.py,$(API_PROTO_FILES))
ADMIN_PYTHON_FILES := $(patsubst $(PROTO_ROOT)/admin/v1/%.proto,$(DST_DIR)/uber/cadence/admin/v1/%_pb2.py,$(ADMIN_PROTO_FILES))
ALL_PYTHON_FILES := $(API_PYTHON_FILES) $(ADMIN_PYTHON_FILES)

# Default target
.PHONY: all
all: $(ALL_PYTHON_FILES)

# Create output directories
$(DST_DIR)/uber/cadence/api/v1/:
	mkdir -p $(DST_DIR)/uber/cadence/api/v1

$(DST_DIR)/uber/cadence/admin/v1/:
	mkdir -p $(DST_DIR)/uber/cadence/admin/v1

# Generate Python files for API protos
$(DST_DIR)/uber/cadence/api/v1/%_pb2.py: $(PROTO_ROOT)/api/v1/%.proto | $(DST_DIR)/uber/cadence/api/v1/
	@echo "Generating Python file for $(PROTO_ROOT)/api/v1/$*.proto"
	protoc --proto_path=$(SRC_DIR) --python_out=$(DST_DIR) $(PROTO_ROOT)/api/v1/$*.proto

# Generate Python files for Admin protos
$(DST_DIR)/uber/cadence/admin/v1/%_pb2.py: $(PROTO_ROOT)/admin/v1/%.proto | $(DST_DIR)/uber/cadence/admin/v1/
	@echo "Generating Python file for $(PROTO_ROOT)/admin/v1/$*.proto"
	protoc --proto_path=$(SRC_DIR) --python_out=$(DST_DIR) $(PROTO_ROOT)/admin/v1/$*.proto

# Clean generated files
.PHONY: clean
clean:
	rm -rf $(DST_DIR)

# Show help
.PHONY: help
help:
	@echo "Available targets:"
	@echo "  all    - Generate all Python proto files (default)"
	@echo "  clean  - Remove all generated files"
	@echo "  help   - Show this help message"
	@echo "  show   - Show what files will be processed"
	@echo ""
	@echo "Generated files will be placed in:"
	@echo "  $(DST_DIR)/uber/cadence/api/v1/  - API proto files"
	@echo "  $(DST_DIR)/uber/cadence/admin/v1/ - Admin proto files"

# Show what will be generated
.PHONY: show
show:
	@echo "Proto files to process:"
	@echo "API:"
	@for file in $(API_PROTO_FILES); do echo "  $$file"; done
	@echo "Admin:"
	@for file in $(ADMIN_PROTO_FILES); do echo "  $$file"; done
	@echo ""
	@echo "Python files to generate:"
	@echo "API:"
	@for file in $(API_PYTHON_FILES); do echo "  $$file"; done
	@echo "Admin:"
	@for file in $(ADMIN_PYTHON_FILES); do echo "  $$file"; done 