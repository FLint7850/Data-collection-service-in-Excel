import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { computed, nextTick, ref, watch } from "vue";
import { useAttributeReview } from "../app/composables/useAttributeReview";
import type { AttributeAssistantContext } from "../app/composables/useAttributeAssistant";
import type { AttributeAllowedValuesContext } from "../app/composables/useAttributeAllowedValues";

const api = vi.hoisted(() => ({
  batch: vi.fn(), products: vi.fn(), product: vi.fn(), batchOperation: vi.fn(),
  donorRecommendations: vi.fn(), productHistory: vi.fn(), updateValue: vi.fn(),
}));
vi.mock("../app/services/attribute-assistant.service", () => ({ attributeAssistantService: api }));

const summary = (id: number) => ({ id, model: `WM-${id}`, name: `Товар ${id}`, brand: "Бренд",
  status: "needs_review", counts: { missing: 1, conflicts: 0, suggestions: 0, outside_template: 0 } });
const page = (offset = 0) => ({ items: Array.from({ length: 80 }, (_, index) => summary(offset + index + 1)),
  total: 4000, matched: 4000, offset, limit: 80, has_more: offset < 3920,
  counts: { all: 4000, needs_review: 4000, ready: 0, conflict: 0, missing: 4000, outside_template: 0 } });
const batch = (id: number) => ({ id, summary: { products: 4000 }, template: { id: 1 } });

function setup() {
  const assistant = {
    busy: ref(""), error: ref(""), tab: ref("start"), inputMode: ref("csv"),
    workspace: ref({ batches: [batch(1)] }), donors: ref([]), selectedTemplateId: ref(1),
    productFile: ref(null), urlsText: ref(""), processingMode: ref("suggest"), chatGpt: ref(null),
    run: async (_key: string, task: () => Promise<unknown>) => task(),
    confirmAction: vi.fn(), promptValue: vi.fn(), loadWorkspace: vi.fn(), notify: vi.fn(), writeRoute: vi.fn(),
  } as unknown as AttributeAssistantContext;
  return useAttributeReview(assistant, { resetAllowedOptionState: vi.fn() } as unknown as AttributeAllowedValuesContext);
}

describe("large attribute batches", () => {
  let review: ReturnType<typeof setup>;
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.stubGlobal("ref", ref);
    vi.stubGlobal("computed", computed);
    vi.stubGlobal("watch", watch);
    vi.stubGlobal("useToast", () => ({ add: vi.fn() }));
    api.batch.mockImplementation(async (id) => batch(id));
    api.products.mockImplementation(async (_id, _query, _status, offset = 0) => page(offset));
    api.batchOperation.mockResolvedValue({ id: "", status: "idle" });
    api.donorRecommendations.mockResolvedValue({ items: [] });
    api.productHistory.mockResolvedValue({ items: [] });
    api.product.mockImplementation(async (id) => ({ ...summary(id), batch_id: 1, values: [{ id: 11 }], sources: [] }));
    review = setup();
  });
  afterEach(() => {
    review.dispose();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("opens only the bounded list and loads attributes on click", async () => {
    await review.openBatch(1);
    expect(api.products).toHaveBeenCalledWith(1, "", "all", 0);
    expect(review.filteredProducts.value).toHaveLength(80);
    expect(review.selectedProduct.value).toBeNull();
    expect(api.product).not.toHaveBeenCalled();
    expect(review.productStatusItems.value[0]?.label).toBe("Все товары (4000)");
    await review.openProduct(4);
    expect(api.product).toHaveBeenCalledTimes(1);
    expect(api.product).toHaveBeenCalledWith(4);
    expect(review.selectedProduct.value?.values).toHaveLength(1);
    expect(review.filteredProducts.value[3]).not.toHaveProperty("values");
  });

  it("supports direct links without loading other product details", async () => {
    await review.openBatch(1, 3999);
    expect(review.selectedProduct.value?.id).toBe(3999);
    expect(api.product).toHaveBeenCalledTimes(1);
    expect(review.filteredProducts.value).toHaveLength(80);
  });

  it("pages the sidebar without discarding the selected product", async () => {
    await review.openBatch(1);
    await review.openProduct(4);
    await review.loadProducts(80);
    expect(review.filteredProducts.value[0]?.id).toBe(81);
    expect(review.filteredProducts.value).toHaveLength(80);
    expect(review.selectedProduct.value?.id).toBe(4);
    expect(api.product).toHaveBeenCalledTimes(1);
  });

  it("debounces server search and rejects stale page responses", async () => {
    await review.openBatch(1);
    let finishOld!: (result: ReturnType<typeof page>) => void;
    api.products.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }));
    const oldRequest = review.loadProducts(80);
    review.productQuery.value = "Машина 3999";
    await nextTick();
    review.productStatusFilter.value = "missing";
    await nextTick();
    await vi.advanceTimersByTimeAsync(250);
    expect(api.products).toHaveBeenLastCalledWith(1, "Машина 3999", "missing", 0);
    finishOld(page(80));
    await oldRequest;
    expect(review.productPage.value?.offset).toBe(0);
  });

  it("ignores a late product response when another batch opens", async () => {
    await review.openBatch(1);
    let finishProduct!: (result: object) => void;
    api.product.mockImplementationOnce(() => new Promise((resolve) => { finishProduct = resolve; }));
    const oldRequest = review.openProduct(4);
    await review.openBatch(2);
    finishProduct({ ...summary(4), batch_id: 1, values: [] });
    await oldRequest;
    expect(review.selectedBatch.value?.id).toBe(2);
    expect(review.selectedProduct.value).toBeNull();
  });

  it("refreshes counters and metadata while retaining the loaded attributes", async () => {
    await review.openBatch(1);
    await review.openProduct(4);
    const updated = page();
    updated.items[3] = { ...summary(4), status: "ready", counts: { missing: 0, conflicts: 0, suggestions: 0, outside_template: 0 } };
    api.products.mockResolvedValueOnce(updated);
    await review.refreshBatch();
    expect(review.selectedProduct.value?.status).toBe("ready");
    expect(review.selectedProduct.value?.values).toHaveLength(1);
    expect(api.product).toHaveBeenCalledTimes(1);
  });

  it("cancels pending searches when switching batches and clears product-specific donors", async () => {
    await review.openBatch(1);
    review.selectedDonors.value = [7];
    review.donorUrlOverrides.value = { 7: "https://example.com/product" };
    review.productQuery.value = "Другой товар";
    await nextTick();
    await review.openBatch(2);
    const requests = api.products.mock.calls.length;
    await vi.advanceTimersByTimeAsync(250);
    expect(api.products).toHaveBeenCalledTimes(requests);
    expect(api.products).toHaveBeenLastCalledWith(2, "", "all", 0);
    expect(review.selectedDonors.value).toEqual([]);
    expect(review.donorUrlOverrides.value).toEqual({});
  });

  it("does not resume polling after leaving the page during a request", async () => {
    let finishOperation!: (result: object) => void;
    api.batchOperation.mockImplementationOnce(() => new Promise((resolve) => { finishOperation = resolve; }));
    await review.openBatch(1);
    review.dispose();
    finishOperation({ id: "operation", status: "running" });
    await vi.advanceTimersByTimeAsync(5000);
    expect(api.batchOperation).toHaveBeenCalledTimes(1);
  });
});
