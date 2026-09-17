CXX ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wextra
SRCS = main.cc yaml.cc dag.cc cli.cc util.cc git.cc apply.cc verify.cc context.cc
OBJS = $(SRCS:.cc=.o)
.PHONY: all clean
all: rfg
rfg: $(OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $(OBJS)
%.o: %.cc
	$(CXX) $(CXXFLAGS) -c $< -o $@
clean:
	rm -f $(OBJS) rfg
