# Linux/macOS: make     Windows (MinGW): make OUT=libroadcare_ds.dll
OUT ?= libroadcare_ds.so
$(OUT): linked_list.c priority_queue.c ds.h
	gcc -O2 -Wall -shared -fPIC -o $(OUT) linked_list.c priority_queue.c
clean:
	rm -f libroadcare_ds.so libroadcare_ds.dll
