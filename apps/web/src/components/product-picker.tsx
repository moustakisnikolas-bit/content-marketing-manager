"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import type { ProductOut } from "@/lib/api";
import { cn } from "@/lib/utils";

const BULK_BACKGROUND_THRESHOLD = 50;

export function ProductPicker({
  products,
  selectedIds,
  onChange,
}: {
  products: ProductOut[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  const [activeCategory, setActiveCategory] = useState<string | null>(null);

  const categories = useMemo(
    () => Array.from(new Set(products.flatMap((p) => p.categories))).sort(),
    [products],
  );

  const visibleProducts = activeCategory ? products.filter((p) => p.categories.includes(activeCategory)) : products;
  const selectedSet = new Set(selectedIds);

  const toggle = (id: string) => {
    onChange(selectedSet.has(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id]);
  };

  const selectAllVisible = () => {
    onChange(Array.from(new Set([...selectedIds, ...visibleProducts.map((p) => p.id)])));
  };

  return (
    <div className="space-y-3">
      {categories.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setActiveCategory(null)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors",
              activeCategory === null ? "border-primary bg-primary/10" : "border-border hover:bg-muted",
            )}
          >
            All
          </button>
          {categories.map((category) => (
            <button
              key={category}
              type="button"
              onClick={() => setActiveCategory(category)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors",
                activeCategory === category ? "border-primary bg-primary/10" : "border-border hover:bg-muted",
              )}
            >
              {category}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{selectedIds.length} selected</p>
        <div className="flex gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={selectAllVisible}>
            Select all{activeCategory ? ` in "${activeCategory}"` : ""}
          </Button>
          {selectedIds.length > 0 && (
            <Button type="button" variant="ghost" size="sm" onClick={() => onChange([])}>
              Clear
            </Button>
          )}
        </div>
      </div>

      <div className="max-h-96 space-y-1 overflow-y-auto rounded-md border border-border p-2">
        {visibleProducts.length === 0 ? (
          <p className="p-2 text-sm text-muted-foreground">No products in this category.</p>
        ) : (
          visibleProducts.map((product) => (
            <label key={product.id} className="flex items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-muted">
              <Checkbox checked={selectedSet.has(product.id)} onCheckedChange={() => toggle(product.id)} />
              <span className="flex-1">
                <span className="font-medium">{product.title}</span>
                {product.categories.length > 0 && (
                  <span className="ml-2 text-xs text-muted-foreground">{product.categories.join(", ")}</span>
                )}
              </span>
            </label>
          ))
        )}
      </div>

      {selectedIds.length >= BULK_BACKGROUND_THRESHOLD && (
        <p className="text-xs text-muted-foreground">
          {selectedIds.length} products selected — this will run in the background, you can leave this page once you
          launch.
        </p>
      )}
    </div>
  );
}
