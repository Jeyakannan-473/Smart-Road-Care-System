#include <stdlib.h>
#include <string.h>
#include "ds.h"
#define PQ_MAX 8192
typedef struct { int id; double score; long ts; } Item;
static Item heap[PQ_MAX];
static int size = 0;

/* 1 if a must come out before b */
static int before(const Item *a, const Item *b) {
    if (a->score != b->score) return a->score > b->score;
    if (a->ts != b->ts) return a->ts < b->ts;
    return a->id < b->id;
}
static void swap(int i, int j) { Item t = heap[i]; heap[i] = heap[j]; heap[j] = t; }
static void up(int i) { while (i > 0 && before(&heap[i], &heap[(i-1)/2])) { swap(i, (i-1)/2); i = (i-1)/2; } }
static void down(int i) {
    for (;;) {
        int l = 2*i+1, r = l+1, m = i;
        if (l < size && before(&heap[l], &heap[m])) m = l;
        if (r < size && before(&heap[r], &heap[m])) m = r;
        if (m == i) return;
        swap(i, m); i = m;
    }
}
int pq_push(int id, double score, long ts) {
    if (size >= PQ_MAX) return -3;
    for (int i = 0; i < size; i++) if (heap[i].id == id) return -2;
    heap[size] = (Item){id, score, ts}; up(size++);
    return 0;
}
int pq_pop(int *id) {
    if (!size) return -1;
    *id = heap[0].id; heap[0] = heap[--size]; down(0);
    return 0;
}
int pq_update(int id, double score) {
    for (int i = 0; i < size; i++) if (heap[i].id == id) { heap[i].score = score; up(i); down(i); return 0; }
    return -1;
}
static int cmp(const void *a, const void *b) { return before(a, b) ? -1 : before(b, a) ? 1 : 0; }
int pq_snapshot(int *ids, int max) {
    static Item tmp[PQ_MAX]; memcpy(tmp, heap, size * sizeof(Item));
    qsort(tmp, size, sizeof(Item), cmp);
    int n = size < max ? size : max;
    for (int i = 0; i < n; i++) ids[i] = tmp[i].id;
    return n;
}
int pq_size(void) { return size; }
void pq_clear(void) { size = 0; }
