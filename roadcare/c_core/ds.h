/* RoadCare core data structures.
 * Linked list : complaint records (id, score, timestamp).
 * Priority queue (binary max-heap): maintenance tasks.
 * Ordering rule: higher score first; ties -> earlier timestamp; then lower id.
 * Return codes: 0 ok, -1 not found / empty, -2 duplicate, -3 out of memory / full. */
#ifndef DS_H
#define DS_H
int  ll_insert(int id, double score, long ts);
int  ll_find(int id);
int  ll_update(int id, double score);
int  ll_delete(int id);
int  ll_count(void);
int  ll_get(int index, int *id, double *score);   /* traversal */
void ll_clear(void);
int  pq_push(int id, double score, long ts);
int  pq_pop(int *id);
int  pq_update(int id, double score);
int  pq_snapshot(int *ids, int max);              /* ordered, non-destructive */
int  pq_size(void);
void pq_clear(void);
#endif
