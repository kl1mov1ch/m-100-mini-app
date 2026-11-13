# PDF processing

The upload UI reserves jobs with `engine=docling` and `selection_policy=specifications`.
Install `backend/docling-requirements.txt` in the isolated environment with
`bash deploy/install_document_parser.sh`. System Tesseract (`rus`, `eng`) and Poppler
are required. `DOCUMENT_DOCLING_PYTHON` may override the parser executable.

Docling's native PDF pipeline extracts text and coordinates without model weights.
Pages without usable text receive local OCR. Ruled cells are reconstructed from
line geometry; numeric cells receive a second OCR pass in batches. Conflicting
readings remain explicit and cannot become an automatic quantity. Native Docling
does not itself infer headings or tables: the application's geometry and source
validation provide these steps.

Conversion starts at the end of the PDF and checkpoints every page. One initial
page, then batches of three, alternate with AI extraction. The first results are
read-only until the entire document has been processed. Every page is eventually
included in the downloadable text archive; drawings and general information are
excluded from work extraction. Unknown page types require scope review. Unruled
or poorly recognized tables may require manual review; no accuracy percentage is
guaranteed.

Each file supplies its own literal section/subsection headings. Context carries
only across consecutive pages in the same file. Confirming a row stores its name,
section, subsection and unit in an owner-specific ORM table. This starts empty,
survives removal of source jobs, and never stores quantities or rates. BM25 selects
relevant confirmed examples and powers text search without additional LLM calls.
This is a confirmed-example memory, not automatic model fine-tuning.

Source hashes and parser revisions protect conversion caches. Deleting a job
revokes download tickets and terminates the parser process group. Rebuilding is
version checked and cannot overwrite published objects. Source files remain
unchanged; marked PDFs include all pages and highlight only used source rows.

The parser runs outside the web process, with one CPU thread and a bounded worker
service (512 MiB maximum). Its memory is released between conversion batches.
