import { App, Button, Checkbox, Input, InputNumber, Modal, Select } from 'antd';
import { ArrowLeft, Download, FileSearch } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Money, nf } from '../lib/format';
import { headers, request } from '../lib/api';
import { downloadReport } from '../lib/report-download';
import type { DocumentJob, DocumentGroup, DocumentSource } from './document-types';
import { DocumentPublishPanel } from './DocumentPublishPanel';
import { CompactRow } from '../components/CompactRow';

function SourcePreview({
	jobId,
	page,
	highlights,
}: {
	jobId: string;
	page: number;
	highlights?: DocumentSource['highlights'];
}) {
	const [open, setOpen] = useState(false),
		[url, setUrl] = useState(''),
		[error, setError] = useState('');
	useEffect(() => {
		if (!open) return;
		const controller = new AbortController();
		let objectUrl = '';
		setError('');
		void fetch(`/api/documents/${jobId}/pages/${page}/preview`, {
			headers: headers(),
			signal: controller.signal,
		})
			.then(async (response) => {
				if (!response.ok) throw new Error('Для этой страницы доступна текстовая цитата.');
				objectUrl = URL.createObjectURL(await response.blob());
				if (controller.signal.aborted) URL.revokeObjectURL(objectUrl);
				else setUrl(objectUrl);
			})
			.catch((error) => {
				if (!controller.signal.aborted) setError((error as Error).message);
			});
		return () => {
			controller.abort();
			URL.revokeObjectURL(objectUrl);
			setUrl('');
		};
	}, [open, jobId, page]);
	return (
		<div className="document-page-preview">
			<Button type="link" onClick={() => setOpen(!open)}>
				{open ? 'Скрыть страницу' : 'Показать страницу PDF'}
			</Button>
			{open &&
				(error ? (
					<p>{error}</p>
				) : url ? (
					<div className="document-highlight-page">
						<a href={url} target="_blank" rel="noreferrer">
							<img src={url} alt={`Страница ${page} исходного PDF`} />
						</a>
						{highlights?.map((box, index) => (
							<span
								key={index}
								style={{
									left: `${box.left}%`,
									top: `${box.top}%`,
									width: `${box.width}%`,
									height: `${box.height}%`,
								}}
							/>
						))}
					</div>
				) : (
					<p>Загружаем страницу…</p>
				))}
		</div>
	);
}

export function DocumentResultsPage({
	job,
	back,
	refresh,
	embedded = false,
	openObject,
}: {
	job: DocumentJob;
	back: () => void;
	refresh: (job: DocumentJob) => void;
	embedded?: boolean;
	openObject?: (id: string) => void;
}) {
	const [category, setCategory] = useState('Все'),
		[status, setStatus] = useState('all'),
		[query, setQuery] = useState(''),
		[editing, setEditing] = useState<DocumentGroup | null>(null),
		[sources, setSources] = useState<DocumentGroup | null>(null),
		[quantity, setQuantity] = useState<string | null>(null),
		[rate, setRate] = useState<string | null>(null),
		[unit, setUnit] = useState('м'),
		[name, setName] = useState(''),
		[editCategory, setEditCategory] = useState(''),
		[section, setSection] = useState(''),
		[subsection, setSubsection] = useState(''),
		[notes, setNotes] = useState(''),
		[resolution, setResolution] = useState<string>(),
		[acknowledge, setAcknowledge] = useState(false),
		[saving, setSaving] = useState(false);
	const { message, modal } = App.useApp();
	const groups = job.payload.groups || [];
	const categories = ['Все', ...new Set(groups.map((row) => row.category))];
	const rows = groups.filter(
		(row) =>
			(category === 'Все' || row.category === category) &&
			(status === 'all' || (status === 'pending' ? !row.confirmed : row.confirmed)) &&
			row.name.toLowerCase().includes(query.toLowerCase()),
	);
	const sections = new Map<string, DocumentGroup[]>();
	for (const row of rows) {
		const label = [row.category, row.section || 'Без раздела', row.subsection]
			.filter(Boolean)
			.join(' · ');
		sections.set(label, [...(sections.get(label) || []), row]);
	}
	const summary = job.payload.summary;
	const readOnly = !['ready', 'needs_review', 'draft'].includes(job.status);
	useEffect(() => {
		setEditing(null);
	}, [readOnly]);
	const needsScope = !!(
		job.payload.coverage?.drawings?.length ||
		job.payload.coverage?.low_ocr?.length ||
		job.payload.coverage?.questions
	);
	const eligible = rows
		.filter(
			(row) =>
				!readOnly &&
				!row.confirmed &&
				!row.issues.length &&
				row.quantity !== null &&
				row.rate != null,
		)
		.slice(0, 100);
	const confirmBatch = async () => {
		setSaving(true);
		try {
			const next = await request<DocumentJob>(`/documents/${job.id}/review`, {
				version: job.updated_at,
				acknowledge_scope: acknowledge,
				items: eligible.map((row) => ({
					group_id: row.id,
					quantity: String(row.quantity),
					rate: row.rate,
					unit: row.unit,
					notes: row.notes,
				})),
			});
			refresh(next);
			message.success(`Подтверждено строк: ${eligible.length}`);
		} catch (error) {
			message.error((error as Error).message);
			refresh(await request<DocumentJob>(`/documents/${job.id}`));
		} finally {
			setSaving(false);
		}
	};
	const choose = (row: DocumentGroup) => {
		setEditing(row);
		setSources(null);
		setQuantity(row.quantity === null ? null : String(row.quantity));
		setRate(row.rate === null ? null : String(row.rate));
		setUnit(row.unit || 'м');
		setName(row.name);
		setEditCategory(row.category);
		setSection(row.section || '');
		setSubsection(row.subsection || '');
		setNotes(row.notes || '');
		setResolution(undefined);
		setAcknowledge(false);
	};
	const confirm = async () => {
		if (readOnly || !editing || quantity === null || rate === null) return;
		setSaving(true);
		try {
			const next = await request<DocumentJob>('/documents/' + job.id + '/groups/' + editing.id, {
				version: job.updated_at,
				quantity,
				rate,
				unit,
				name,
				category: editCategory,
				section,
				subsection,
				notes,
				resolution,
				acknowledge_scope: acknowledge,
			});
			refresh(next);
			setEditing(null);
			message.success('Позиция подтверждена');
		} catch (error) {
			message.error((error as Error).message);
			const fresh = await request<DocumentJob>('/documents/' + job.id);
			refresh(fresh);
		} finally {
			setSaving(false);
		}
	};
	const exportFile = async (final = false) => {
		try {
			await downloadReport('/documents/' + job.id + '/export.xlsx' + (final ? '?final=true' : ''));
		} catch (error) {
			message.error((error as Error).message);
		}
	};
	const rebuild = () =>
		modal.confirm({
			title: 'Пересобрать выборку?',
			icon: null,
			content:
				'Будут заново отобраны спецификации и разделы этого файла. Текущая выборка заменится. Подтверждённые примеры названий сохранятся.',
			okText: 'Пересобрать',
			cancelText: 'Отмена',
			onOk: async () => {
				refresh(
					await request<DocumentJob>(`/documents/${job.id}/rebuild`, { version: job.updated_at }),
				);
			},
		});
	return (
		<div className="document-page document-results-page">
			{!embedded && (
				<button className="back-link" onClick={back}>
					<ArrowLeft size={16} />
					Документы
				</button>
			)}
			<div className="page-title document-results-title">
				<div>
					{embedded ? <h2>Данные файла</h2> : <h1>Выборка работ</h1>}
					{['queued', 'ai_queued', 'extracting', 'analysing'].includes(job.status) && (
						<small className="page-context">Предварительные данные · обработка продолжается</small>
					)}
					{!embedded && <small className="page-context document-filename">{job.name}</small>}
				</div>
				{!readOnly && (
					<Button type="text" onClick={rebuild}>
						Пересобрать
					</Button>
				)}
			</div>
			<section className="document-result-summary">
				<div>
					<span>
						<small>Подтверждено</small>
						<strong>
							{summary?.confirmed || 0} / {groups.length}
						</strong>
					</span>
					<span>
						<small>Проверенная сумма</small>
						<strong>
							<Money value={summary?.amount || 0} />
						</strong>
					</span>
				</div>
			</section>
			<details className="document-checks">
				<summary>
					Проверка источников{' '}
					<span>
						· {job.processed}/{job.pages} стр.
						{job.payload.questions?.length ? ` · ${job.payload.questions.length} вопросов` : ''}
					</span>
				</summary>
				<p>{job.payload.query}</p>
				<p>В сумме — только проверенные строки с расценками.</p>
				{job.payload.selection_complete && (
					<p>
						Отобраны страницы: {job.payload.selected_specifications?.join(', ') || 'не найдены'}.
						Остальные листы не используются для подсчёта и выделения.
					</p>
				)}
				{!job.payload.coverage?.complete && (
					<p>Обработка неполная — итоговый отчёт пока недоступен.</p>
				)}
				{needsScope && (
					<p>
						Есть вопросы к полноте или качеству распознавания. Геометрические длины и площади по
						изображениям не измерялись. Проверьте источники отмеченных строк.
					</p>
				)}
				{!!job.payload.questions?.length && (
					<ul>
						{job.payload.questions.map((question, index) => (
							<li key={index}>{question}</li>
						))}
					</ul>
				)}
			</details>
			<div className="document-results-filters">
				<Input.Search
					placeholder="Найти работу"
					value={query}
					onChange={(event) => {
						setQuery(event.target.value);
					}}
				/>
				<div>
					<Select
						aria-label="Категория выборки"
						value={category}
						onChange={(value) => {
							setCategory(value);
						}}
						options={categories.map((value) => ({ value, label: value }))}
					/>
					<Select
						aria-label="Проверка строк"
						value={status}
						onChange={(value) => {
							setStatus(value);
						}}
						options={[
							{ value: 'all', label: 'Все строки' },
							{ value: 'pending', label: 'Требуют проверки' },
							{ value: 'confirmed', label: 'Подтверждены' },
						]}
					/>
				</div>
			</div>
			<div className="document-works document-section-list" aria-label="Работы из документа">
				{[...sections].map(([label, sectionRows]) => (
					<section className="document-section" key={label}>
						<h3>
							{label} <small>{sectionRows.length}</small>
						</h3>
						<div className="compact-list">
							{sectionRows.map((row) => (
								<CompactRow
									key={row.id}
									className="document-review-row"
									title={row.name}
									description={
										<>
											{row.category} ·{' '}
											{row.quantity === null
												? 'Уточните объём'
												: nf.format(Number(row.quantity)) + ' ' + row.unit}
										</>
									}
									value={
										row.rate !== null ? (
											<>
												<Money value={Number(row.rate)} /> / {row.unit}
											</>
										) : (
											'Нет расценки'
										)
									}
									meta={
										row.confirmed ? 'Проверено' : row.issues.length ? 'Нужна проверка' : 'Черновик'
									}
									attention={!row.confirmed && !!row.issues.length}
									onClick={() => choose(row)}
								/>
							))}
						</div>
					</section>
				))}
				{!rows.length && <p className="compact-empty">Работ по этим фильтрам нет</p>}
			</div>
			{eligible.length > 0 && (
				<section className="document-batch-review">
					<small>
						Строки с расценками без спорных объёмов. Подтвердите их после проверки источников.
					</small>
					{needsScope && !job.payload.acknowledge_scope && (
						<Checkbox
							checked={acknowledge}
							onChange={(event) => setAcknowledge(event.target.checked)}
						>
							Полнота выборки и вопросы проверены
						</Checkbox>
					)}
					<Button type="primary" loading={saving} onClick={() => void confirmBatch()}>
						Подтвердить строки · {eligible.length}
					</Button>
				</section>
			)}
			<div className="document-export-actions">
				<Button
					icon={<FileSearch size={16} />}
					onClick={() =>
						void downloadReport(`/documents/${job.id}/marked.pdf`).catch((error) =>
							message.error(error.message),
						)
					}
				>
					PDF с выделением
				</Button>
				<Button
					icon={<Download size={16} />}
					onClick={() => void exportFile(['ready', 'published'].includes(job.status))}
				>
					{['ready', 'published'].includes(job.status) ? 'Скачать Excel' : 'Excel-черновик'}
				</Button>
			</div>
			<small className="document-highlight-legend">
				Жёлтым в PDF отмечены использованные источники.
			</small>
			<DocumentPublishPanel job={job} refresh={refresh} openObject={openObject} />
			<Modal
				className="document-work-sheet"
				title={sources ? 'Источники позиции' : editing?.name}
				open={!!editing}
				onCancel={() => (sources ? setSources(null) : !saving && setEditing(null))}
				confirmLoading={saving}
				destroyOnHidden
				{...(sources
					? { footer: <Button onClick={() => setSources(null)}>К позиции</Button> }
					: readOnly
						? { footer: <Button onClick={() => setEditing(null)}>Готово</Button> }
						: {})}
				okText="Подтвердить"
				cancelText="Отмена"
				onOk={() => !sources && void confirm()}
				okButtonProps={{
					disabled:
						quantity === null ||
						rate === null ||
						((editing?.issues.length || 0) > 0 && !resolution),
				}}
			>
				{sources ? (
					<div className="document-source">
						{sources.sources.map((source, index) => (
							<section key={index}>
								<strong>
									Страница {source.page} · {source.original_quantity ?? 'Не определено'}{' '}
									{source.original_unit}
								</strong>
								<blockquote>{source.quote}</blockquote>
								{source.question && <p className="document-question">{source.question}</p>}
								<SourcePreview jobId={job.id} page={source.page} highlights={source.highlights} />
								{source.conversion_factor && source.conversion_factor !== '1' && (
									<p>
										Приведено к {source.unit}: {source.quantity}
									</p>
								)}
							</section>
						))}
					</div>
				) : readOnly ? (
					<div className="document-review-form">
						<dl className="position-totals">
							<div>
								<dt>По смете</dt>
								<dd>
									{editing?.quantity ?? 'Не определено'} {editing?.unit}
								</dd>
							</div>
							<div>
								<dt>За единицу</dt>
								<dd>
									{editing?.rate != null ? <Money value={Number(editing.rate)} /> : 'Не указано'}
								</dd>
							</div>
						</dl>
						<p>
							{[editing?.category, editing?.section, editing?.subsection]
								.filter(Boolean)
								.join(' · ')}
						</p>
						{editing?.notes && <p>{editing.notes}</p>}
						<Button icon={<FileSearch size={16} />} onClick={() => setSources(editing)}>
							Источники · {editing?.sources.length}
						</Button>
					</div>
				) : (
					<div className="document-review-form">
						<div className="document-work-total">
							<span>Сумма по позиции</span>
							<strong>
								{quantity !== null && rate !== null ? (
									<Money value={Number(quantity) * Number(rate)} />
								) : (
									'Укажите объём и расценку'
								)}
							</strong>
						</div>
						<details className="document-details document-edit-details">
							<summary>Название и раздел</summary>
							<label>
								Название работы
								<Input
									value={name}
									maxLength={300}
									onChange={(event) => setName(event.target.value)}
								/>
							</label>
							<label>
								Категория
								<Select
									value={editCategory}
									onChange={setEditCategory}
									options={[
										'Вентиляция',
										'Отопление',
										'Водоснабжение',
										'Канализация',
										'Кондиционирование',
										'Электроснабжение',
										'Автоматика',
										'Прочее',
									].map((value) => ({ value, label: value }))}
								/>
							</label>
							<label>
								Раздел в этом файле
								<Input
									value={section}
									onChange={(e) => setSection(e.target.value)}
									maxLength={160}
									placeholder="Дословный заголовок из файла"
								/>
							</label>
							<label>
								Подраздел
								<Input
									value={subsection}
									onChange={(e) => setSubsection(e.target.value)}
									maxLength={160}
								/>
							</label>
						</details>
						{editing?.issues.map((issue) => (
							<p className="document-question" key={issue}>
								{issue}
							</p>
						))}
						{editing && (
							<Button
								type="text"
								icon={<FileSearch size={16} />}
								onClick={() => setSources(editing)}
							>
								Проверить источники
							</Button>
						)}
						<div className="document-input-pair">
							<label>
								Единица измерения
								<Select
									value={unit}
									onChange={setUnit}
									options={['м', 'м²', 'м³', 'шт.', 'кг', 'компл.', 'чел·ч', 'чел·дн'].map(
										(value) => ({
											value,
											label: value,
										}),
									)}
								/>
							</label>
							<label>
								Объём
								<InputNumber
									stringMode
									min="0"
									max="1000000000"
									value={quantity}
									onChange={setQuantity}
									controls={false}
								/>
							</label>
						</div>
						<label>
							Расценка за {unit}, BYN
							<InputNumber
								stringMode
								min="0"
								max="1000000000"
								value={rate}
								onChange={setRate}
								controls={false}
							/>
						</label>
						<details className="document-details document-edit-details">
							<summary>Примечание</summary>
							<label>
								Примечания
								<Input.TextArea
									value={notes}
									maxLength={2000}
									autoSize={{ minRows: 2, maxRows: 5 }}
									onChange={(event) => setNotes(event.target.value)}
								/>
							</label>
						</details>
						{!!editing?.issues.length && (
							<label>
								Как проверен спорный объём
								<Select
									value={resolution}
									onChange={(value) => {
										setResolution(value);
										if (value === 'sum' && editing.proposed_quantity !== null)
											setQuantity(String(editing.proposed_quantity));
										if (value === 'one' && editing.sources[0]?.quantity !== null)
											setQuantity(String(editing.sources[0].quantity));
									}}
									placeholder="Выберите решение"
									options={[
										{
											value: 'sum',
											label: 'Работы разные — сложить объёмы',
											disabled: editing.proposed_quantity === null,
										},
										{
											value: 'one',
											label: 'Повтор одной позиции — учесть один раз',
											disabled: editing.sources[0]?.quantity === null,
										},
										{ value: 'manual', label: 'Объём проверен и уточнён вручную' },
									]}
								/>
							</label>
						)}
						{!!(
							job.payload.coverage?.drawings?.length ||
							job.payload.coverage?.low_ocr?.length ||
							job.payload.coverage?.questions
						) &&
							!job.payload.acknowledge_scope && (
								<Checkbox
									checked={acknowledge}
									onChange={(event) => setAcknowledge(event.target.checked)}
								>
									Источники и полнота проверены. Геометрия чертежей не измерялась.
								</Checkbox>
							)}
					</div>
				)}
			</Modal>
		</div>
	);
}
