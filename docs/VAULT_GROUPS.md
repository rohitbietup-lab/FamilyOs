# Vault document groups

The Vault shows category cards with counts and groups the document list under
category headings. Selecting a card filters the list to that category and resets
pagination. Archive, starred and due-date filters are retained. Counts follow
those filters and include all matching documents, not only the current page.
Each category can span multiple pages. Empty categories remain visible with zero
documents so missing groups are clear.

Other / Needs review is the existing Other category. Use it for ambiguous files
whose titles and filenames do not provide enough evidence to classify them.
Edit details lets the owner add a clear title and choose the final category.
Archived documents stay separate and can be grouped with the archive filter.
Category changes do not move, decrypt to disk, or rewrite encrypted objects.

Local categorization was performed from existing titles and filenames, without
inventing labels from ambiguous image names. A consistent private SQLite backup
was taken before changes; changes increment document revisions and create audit
events. No documents were deleted or unarchived. Private metadata and backups are
not committed to the repository.

Validation: 28 Vault tests pass, including category counts, category selection,
pagination reset, archived/starred filters and existing Vault protections. Ruff
passes. The live category cards and Identity filter were verified in the browser.
