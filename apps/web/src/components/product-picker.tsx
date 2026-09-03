"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { api, type CategoryOut, type ProductOut } from "@/lib/api";
import { cn } from "@/lib/utils";

const BULK_BACKGROUND_THRESHOLD = 50;

interface CategoryNode {
  category: CategoryOut;
  children: CategoryNode[];
}

function buildCategoryTree(categories: CategoryOut[]): CategoryNode[] {
  const byId = new Map<string, CategoryNode>(
    categories.map((c) => [c.external_category_id, { category: c, children: [] }]),
  );
  const roots: CategoryNode[] = [];
  for (const node of byId.values()) {
    const parentId = node.category.parent_external_category_id;
    const parent = parentId ? byId.get(parentId) : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }
  const sortRecursive = (nodes: CategoryNode[]) => {
    nodes.sort((a, b) => a.category.name.localeCompare(b.category.name));
    for (const node of nodes) sortRecursive(node.children);
  };
  sortRecursive(roots);
  return roots;
}

// A parent category's filter includes products from every category
// beneath it too, not just products tagged with that exact name.
function namesInScope(node: CategoryNode): string[] {
  return [node.category.name, ...node.children.flatMap(namesInScope)];
}

function CategoryTreeItem({
  node,
  depth,
  activeName,
  onSelect,
}: {
  node: CategoryNode;
  depth: number;
  activeName: string | null;
  onSelect: (name: string) => void;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={() => onSelect(node.category.name)}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        className={cn(
          "block w-full rounded-md py-1.5 pr-2 text-left text-xs transition-colors",
          activeName === node.category.name ? "bg-primary/10 font-medium text-primary" : "hover:bg-muted",
        )}
      >
        {node.category.name}
      </button>
      {node.children.map((child) => (
        <CategoryTreeItem key={child.category.id} node={child} depth={depth + 1} activeName={activeName} onSelect={onSelect} />
      ))}
    </div>
  );
}

export function ProductPicker({
  products,
  selectedIds,
  onChange,
}: {
  products: ProductOut[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  const [activeCategory, setActiveCategory] = useState<CategoryNode | null>(null);

  const { data: rawCategories } = useQuery({ queryKey: ["commerce", "categories"], queryFn: api.listCategories });
  const categoryTree = useMemo(() => buildCategoryTree(rawCategories ?? []), [rawCategories]);

  // Products whose category names don't match anything in the synced tree
  // (sync hasn't run yet, or the category was since removed on the store)
  // still show up under "All" — a flat fallback list, same as before the
  // tree existed, rather than a hierarchy built from product names alone.
  const flatCategoryNames = useMemo(
    () => Array.from(new Set(products.flatMap((p) => p.categories))).sort(),
    [products],
  );
  const hasTree = categoryTree.length > 0;

  const activeScope = activeCategory ? new Set(namesInScope(activeCategory)) : null;
  const visibleProducts = activeScope
    ? products.filter((p) => p.categories.some((name) => activeScope.has(name)))
    : products;
  const selectedSet = new Set(selectedIds);

  const toggle = (id: string) => {
    onChange(selectedSet.has(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id]);
  };

  const selectAllVisible = () => {
    onChange(Array.from(new Set([...selectedIds, ...visibleProducts.map((p) => p.id)])));
  };

  const findNodeByName = (nodes: CategoryNode[], name: string): CategoryNode | null => {
    for (const node of nodes) {
      if (node.category.name === name) return node;
      const found = findNodeByName(node.children, name);
      if (found) return found;
    }
    return null;
  };

  return (
    <div className="space-y-3 sm:flex sm:items-start sm:gap-4 sm:space-y-0">
      {(hasTree || flatCategoryNames.length > 0) && (
        <div className="max-h-64 shrink-0 space-y-0.5 overflow-y-auto rounded-md border border-border p-1 sm:w-48">
          <button
            type="button"
            onClick={() => setActiveCategory(null)}
            className={cn(
              "block w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors",
              activeCategory === null ? "bg-primary/10 font-medium text-primary" : "hover:bg-muted",
            )}
          >
            All
          </button>
          {hasTree
            ? categoryTree.map((node) => (
                <CategoryTreeItem
                  key={node.category.id}
                  node={node}
                  depth={0}
                  activeName={activeCategory?.category.name ?? null}
                  onSelect={(name) => {
                    const node = findNodeByName(categoryTree, name);
                    setActiveCategory(node);
                  }}
                />
              ))
            : // No synced category tree yet (store not connected, or sync
              // hasn't run) — fall back to a flat list of names read
              // straight off the products, same as before this feature.
              flatCategoryNames.map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() =>
                    setActiveCategory({
                      category: { id: name, external_category_id: name, name, parent_external_category_id: null },
                      children: [],
                    })
                  }
                  className={cn(
                    "block w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors",
                    activeCategory?.category.name === name ? "bg-primary/10 font-medium text-primary" : "hover:bg-muted",
                  )}
                >
                  {name}
                </button>
              ))}
        </div>
      )}

      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">{selectedIds.length} selected</p>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={selectAllVisible}>
              Select all{activeCategory ? ` in "${activeCategory.category.name}"` : ""}
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
    </div>
  );
}
