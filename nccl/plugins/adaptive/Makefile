CXX ?= g++

PLUGIN_SO := libnccl-adaptive.so
SRCS := adaptive_plugin.cc
OBJS := $(SRCS:.cc=.o)

CXXFLAGS ?= -std=c++17 -fPIC -Wall -Wextra -O2
LDFLAGS ?= -shared

.PHONY: all clean

all: $(PLUGIN_SO)

$(PLUGIN_SO): $(OBJS)
	$(CXX) $(LDFLAGS) -Wl,-soname,$(PLUGIN_SO) -o $@ $(OBJS) -lpthread

%.o: %.cc
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(PLUGIN_SO)
