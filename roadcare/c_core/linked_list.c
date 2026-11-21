#include <stdlib.h>
#include "ds.h"
typedef struct Node { int id; double score; long ts; struct Node *next; } Node;
static Node *head = NULL;
static int count = 0;

int ll_insert(int id, double score, long ts) {
    if (ll_find(id) == 1) return -2;
    Node *n = malloc(sizeof *n);
    if (!n) return -3;
    n->id = id; n->score = score; n->ts = ts; n->next = NULL;
    if (!head) head = n; else { Node *p = head; while (p->next) p = p->next; p->next = n; }
    count++;
    return 0;
}
int ll_find(int id) { for (Node *p = head; p; p = p->next) if (p->id == id) return 1; return 0; }
int ll_update(int id, double score) {
    for (Node *p = head; p; p = p->next) if (p->id == id) { p->score = score; return 0; }
    return -1;
}
int ll_delete(int id) {
    Node *prev = NULL;
    for (Node *p = head; p; prev = p, p = p->next)
        if (p->id == id) { if (prev) prev->next = p->next; else head = p->next; free(p); count--; return 0; }
    return -1;
}
int ll_count(void) { return count; }
int ll_get(int index, int *id, double *score) {
    Node *p = head;
    while (p && index-- > 0) p = p->next;
    if (!p) return -1;
    *id = p->id; *score = p->score;
    return 0;
}
void ll_clear(void) { while (head) { Node *n = head->next; free(head); head = n; } count = 0; }
