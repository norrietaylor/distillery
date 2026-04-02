/**
 * Offline Queue Module for the Distillery Browser Extension.
 *
 * Persists queued MCP operations in chrome.storage.local and replays them
 * in FIFO order when connectivity is restored. Enforces a 100-item cap,
 * dropping the oldest entry when the cap is exceeded.
 *
 * Exports (via globalThis): OfflineQueue
 */

/* exported OfflineQueue */

/**
 * Storage key used for the offline queue in chrome.storage.local.
 * @type {string}
 */
const QUEUE_STORAGE_KEY = 'offlineQueue';

/**
 * Maximum number of items allowed in the queue.
 * @type {number}
 */
const QUEUE_MAX_SIZE = 100;

/**
 * Offline queue for MCP operations.
 *
 * Each queued item has the shape:
 *   { id: string, payload: object, timestamp: string, retryCount: number }
 *
 * Usage:
 *   const queue = new OfflineQueue();
 *   await queue.enqueue({ toolName: 'distillery_store', args: { content: '...' } });
 *   const items = await queue.getQueue();
 *   await queue.removeItem(items[0].id);
 */
class OfflineQueue {
  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Add an operation to the end of the queue.
   *
   * If the queue already contains QUEUE_MAX_SIZE items, the oldest item is
   * dropped and a warning is logged.
   *
   * @param {object} payload - The operation payload (toolName, args).
   * @returns {Promise<{id: string, dropped: boolean}>} The new item id and
   *   whether an old item was dropped to make room.
   */
  async enqueue(payload) {
    const queue = await this._load();

    const item = {
      id: this._generateId(),
      payload,
      timestamp: new Date().toISOString(),
      retryCount: 0,
    };

    let dropped = false;
    if (queue.length >= QUEUE_MAX_SIZE) {
      const removed = queue.shift();
      console.warn(
        '[offline-queue] Queue at capacity (%d). Dropping oldest item: %s',
        QUEUE_MAX_SIZE,
        removed.id
      );
      dropped = true;
    }

    queue.push(item);
    await this._save(queue);

    return { id: item.id, dropped };
  }

  /**
   * Remove and return the oldest item in the queue.
   *
   * @returns {Promise<object|null>} The dequeued item, or null if the queue
   *   is empty.
   */
  async dequeue() {
    const queue = await this._load();
    if (queue.length === 0) {
      return null;
    }

    const item = queue.shift();
    await this._save(queue);
    return item;
  }

  /**
   * Return the full queue without modifying it.
   *
   * @returns {Promise<Array<object>>}
   */
  async getQueue() {
    return this._load();
  }

  /**
   * Return the number of items in the queue.
   *
   * @returns {Promise<number>}
   */
  async getCount() {
    const queue = await this._load();
    return queue.length;
  }

  /**
   * Remove a specific item from the queue by its id.
   *
   * @param {string} id - The item id to remove.
   * @returns {Promise<boolean>} True if the item was found and removed.
   */
  async removeItem(id) {
    const queue = await this._load();
    const index = queue.findIndex((item) => item.id === id);
    if (index === -1) {
      return false;
    }

    queue.splice(index, 1);
    await this._save(queue);
    return true;
  }

  /**
   * Increment the retry count for a specific item.
   *
   * @param {string} id - The item id to update.
   * @returns {Promise<boolean>} True if the item was found and updated.
   */
  async incrementRetry(id) {
    const queue = await this._load();
    const item = queue.find((entry) => entry.id === id);
    if (!item) {
      return false;
    }

    item.retryCount += 1;
    await this._save(queue);
    return true;
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  /**
   * Load the queue array from chrome.storage.local.
   *
   * @returns {Promise<Array<object>>}
   */
  async _load() {
    const data = await chrome.storage.local.get(QUEUE_STORAGE_KEY);
    return Array.isArray(data[QUEUE_STORAGE_KEY]) ? data[QUEUE_STORAGE_KEY] : [];
  }

  /**
   * Persist the queue array to chrome.storage.local.
   *
   * @param {Array<object>} queue
   * @returns {Promise<void>}
   */
  async _save(queue) {
    await chrome.storage.local.set({ [QUEUE_STORAGE_KEY]: queue });
  }

  /**
   * Generate a simple unique id for a queue item.
   *
   * @returns {string}
   */
  _generateId() {
    return `q-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }
}

// Export to global scope for importScripts consumers.
if (typeof globalThis !== 'undefined') {
  globalThis.OfflineQueue = OfflineQueue;
}
