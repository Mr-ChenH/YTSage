export type PaginationItem = number | 'ellipsis';

export function paginationItems(currentPage: number, totalPages: number): PaginationItem[] {
  if (totalPages <= 9) return Array.from({ length: totalPages }, (_, index) => index + 1);

  const pages = new Set<number>([1, totalPages]);
  for (let item = currentPage - 2; item <= currentPage + 2; item += 1) {
    if (item > 1 && item < totalPages) pages.add(item);
  }
  if (currentPage <= 4) [2, 3, 4, 5].forEach((item) => pages.add(item));
  if (currentPage >= totalPages - 3) {
    [totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1].forEach((item) => pages.add(item));
  }

  const sortedPages = [...pages].filter((item) => item >= 1 && item <= totalPages).sort((a, b) => a - b);
  return sortedPages.flatMap((item, index) => {
    const previous = sortedPages[index - 1];
    return previous && item - previous > 1 ? ['ellipsis' as const, item] : [item];
  });
}
