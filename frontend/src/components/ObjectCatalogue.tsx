import { Button, Empty, Input, Modal, Pagination, Select, Tag } from 'antd';
import { ChevronDown, ChevronRight, Search, SlidersHorizontal, TriangleAlert } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import type { WorkspaceView } from '../App';
import { countLabel, Money, unit } from '../lib/format';
import type { Position } from '../types';
import { BitrixReadStatus } from './BitrixReadStatus';
import { estimateStatus, formatVolume, positionOverrun } from '../lib/position-volume';
import {
	catalogueCategories,
	catalogueCategory,
	catalogueStatusMatches,
	catalogueValues,
	selectCatalogue,
	type CatalogueCategory,
	type CatalogueSort,
	type CatalogueStatus,
} from '../lib/catalogue';
import './object-catalogue.css';

const statusOptions = [
	{ value: 'all', label: 'Все состояния' },
	{ value: 'remaining', label: 'Есть остаток' },
	{ value: 'completed', label: 'Выполнено по смете' },
	{ value: 'overrun', label: 'Перерасход' },
];
const sortOptions = [
	{ value: 'source', label: 'Как в таблице' },
	{ value: 'name', label: 'По названию' },
	{ value: 'remaining', label: 'Сначала больший остаток' },
	{ value: 'rate', label: 'Сначала большая расценка' },
];

function CatalogueGroup({
	title,
	positions,
	initiallyOpen,
	duplicateNames,
	onView,
}: {
	title: string;
	positions: Position[];
	initiallyOpen: boolean;
	duplicateNames: Set<string>;
	onView: (position: Position) => void;
}) {
	const [open, setOpen] = useState(initiallyOpen);
	const [page, setPage] = useState(1);
	const groupElement = useRef<HTMLElement>(null);
	const excess = positions.filter((position) => catalogueStatusMatches(position, 'overrun')).length;
	const currentPage = Math.min(page, Math.max(1, Math.ceil(positions.length / 8)));
	return (
		<section className="catalogue-group" ref={groupElement}>
			<button
				className="catalogue-group-toggle"
				type="button"
				aria-expanded={open}
				onClick={() => setOpen((value) => !value)}
			>
				<span>
					<strong>{title}</strong>
					<small>
						{countLabel(positions.length, 'позиция', 'позиции', 'позиций')}
						{excess > 0 && (
							<span className="catalogue-excess-count"> · {excess} с перерасходом</span>
						)}
					</small>
				</span>
				<ChevronDown size={18} className={open ? 'is-open' : ''} aria-hidden />
			</button>
			{open && (
				<div className="catalogue-group-body">
					<ul className="object-catalogue">
						{positions.slice((currentPage - 1) * 8, currentPage * 8).map((position) => {
							const values = catalogueValues(position);
							const overrun = positionOverrun(position);
							const excess = overrun || values.completed > values.planned + 1e-8;
							return (
								<li key={position.id} className={excess ? 'catalogue-overrun' : undefined}>
									<button
										type="button"
										className="catalogue-position"
										onClick={() => onView(position)}
									>
										<b>{position.name}</b>
										{duplicateNames.has(position.name) && (
											<small className="catalogue-source">
												{position.source_sheet || position.section} · строка {position.source_row}
											</small>
										)}
										<span className="catalogue-quantity-line">
											<span>
												План <strong>{formatVolume(values.planned, position.unit)}</strong>
											</span>
											<span>
												Факт <strong>{formatVolume(values.completed, position.unit)}</strong>
											</span>
										</span>
										<span className={'catalogue-position-foot' + (excess ? ' has-excess' : '')}>
											<span>
												{excess && <TriangleAlert size={13} aria-hidden />}
												{excess && values.completed <= values.planned
													? 'Проверьте остаток'
													: estimateStatus(values, position.unit)}
											</span>
											<span>
												<Money value={values.rate} /> / {unit(position.unit)}
											</span>
										</span>
										{position.hidden && (
											<Tag className="status-tag-attention">Скрыта из подбора</Tag>
										)}
										<ChevronRight className="catalogue-position-arrow" size={16} aria-hidden />
									</button>
								</li>
							);
						})}
					</ul>
					{positions.length > 8 && (
						<div className="catalogue-pagination">
							<small>
								{(currentPage - 1) * 8 + 1}–{Math.min(currentPage * 8, positions.length)} из{' '}
								{positions.length}
							</small>
							<Pagination
								simple={{ readOnly: true }}
								current={currentPage}
								pageSize={8}
								total={positions.length}
								showSizeChanger={false}
								onChange={(value) => {
									setPage(value);
									groupElement.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
								}}
							/>
						</div>
					)}
				</div>
			)}
		</section>
	);
}

export function ObjectCatalogue({
	workspace,
	onView,
}: {
	workspace: WorkspaceView;
	onView: (position: Position) => void;
}) {
	const [query, setQuery] = useState('');
	const [category, setCategory] = useState<CatalogueCategory>('all');
	const [status, setStatus] = useState<CatalogueStatus>('all');
	const [section, setSection] = useState('all');
	const [sort, setSort] = useState<CatalogueSort>('source');
	const [filtersOpen, setFiltersOpen] = useState(false);
	const { allPositions, openObjectSection } = workspace;
	const sections = useMemo(
		() =>
			[...new Set(allPositions.map((position) => position.section).filter(Boolean))].sort((a, b) =>
				a.localeCompare(b, 'ru'),
			),
		[allPositions],
	);
	const matching = useMemo(
		() => selectCatalogue(allPositions, { query, category, status, section, sort }),
		[allPositions, query, category, status, section, sort],
	);
	const grouped = useMemo(() => {
		const groups = new Map<string, { title: string; positions: Position[] }>();
		for (const position of matching) {
			const kind = catalogueCategory(position);
			const key = JSON.stringify([kind, position.section]);
			const categoryTitle = catalogueCategories.find((item) => item.value === kind)!.title;
			const title = position.section ? `${position.section} · ${categoryTitle}` : categoryTitle;
			if (!groups.has(key)) groups.set(key, { title, positions: [] });
			groups.get(key)!.positions.push(position);
		}
		return [...groups.entries()];
	}, [matching]);
	const duplicateNames = useMemo(() => {
		const names = new Set<string>(),
			duplicates = new Set<string>();
		for (const position of allPositions) {
			if (names.has(position.name)) duplicates.add(position.name);
			names.add(position.name);
		}
		return duplicates;
	}, [allPositions]);
	const reset = () => {
		setQuery('');
		setStatus('all');
		setSection('all');
		setSort('source');
		setCategory('all');
	};
	const filterCount =
		Number(status !== 'all') + Number(section !== 'all') + Number(sort !== 'source');
	const context = JSON.stringify([category, status, section, sort, query]);
	if (!allPositions.length)
		return (
			<section className="object-panel">
				<Empty description="Смета пуста" image={Empty.PRESENTED_IMAGE_SIMPLE} />
				<Button type="primary" onClick={() => openObjectSection('table')}>
					Добавить таблицу
				</Button>
			</section>
		);
	return (
		<section className="object-panel catalogue-panel">
			<div className="catalogue-heading">
				<h2>Смета</h2>
				<small>{countLabel(allPositions.length, 'позиция', 'позиции', 'позиций')}</small>
			</div>
			<BitrixReadStatus workspace={workspace} />
			<div className="catalogue-controls">
				<Input
					aria-label="Найти работу в смете"
					placeholder="Найти позицию"
					prefix={<Search size={17} />}
					allowClear
					value={query}
					onChange={(event) => setQuery(event.target.value)}
				/>
				<Button
					aria-label="Фильтры и сортировка сметы"
					icon={<SlidersHorizontal size={18} />}
					onClick={() => setFiltersOpen(true)}
					className={filterCount ? 'catalogue-filter-active' : ''}
				>
					{filterCount || null}
				</Button>
			</div>
			<div className="catalogue-categories" role="group" aria-label="Тип позиций сметы">
				{catalogueCategories.map((item) => (
					<button
						key={item.value}
						type="button"
						aria-pressed={category === item.value}
						title={item.title}
						onClick={() => setCategory(item.value)}
					>
						<span>{item.label}</span>
						<small>
							{
								allPositions.filter(
									(position) => item.value === 'all' || catalogueCategory(position) === item.value,
								).length
							}
						</small>
					</button>
				))}
			</div>
			<div className="catalogue-result-heading">
				<small>
					{countLabel(matching.length, 'позиция', 'позиции', 'позиций')}
					{status !== 'all'
						? ' · ' + statusOptions.find((item) => item.value === status)!.label
						: ''}
					{section !== 'all' ? ' · ' + section : ''}
				</small>
				{(filterCount > 0 || query || category !== 'all') && (
					<Button type="text" size="small" onClick={reset}>
						Сбросить
					</Button>
				)}
			</div>
			<div className="catalogue-groups">
				{grouped.map(([key, group]) => (
					<CatalogueGroup
						key={context + key}
						title={group.title}
						positions={group.positions}
						initiallyOpen={grouped.length === 1 || (!!query.trim() && matching.length <= 8)}
						duplicateNames={duplicateNames}
						onView={onView}
					/>
				))}
			</div>
			{!matching.length && (
				<Empty
					description="Нет позиций по выбранным условиям"
					image={Empty.PRESENTED_IMAGE_SIMPLE}
				/>
			)}
			<Modal
				title="Фильтры сметы"
				open={filtersOpen}
				onCancel={() => setFiltersOpen(false)}
				footer={
					<>
						<Button onClick={reset}>Сбросить</Button>
						<Button type="primary" onClick={() => setFiltersOpen(false)}>
							Показать ({matching.length})
						</Button>
					</>
				}
			>
				<div className="catalogue-filter-form">
					<label>
						Состояние
						<Select
							aria-label="Состояние позиций"
							value={status}
							onChange={setStatus}
							options={statusOptions}
						/>
					</label>
					{sections.length > 1 && (
						<label>
							Раздел
							<Select
								aria-label="Раздел сметы"
								value={section}
								onChange={setSection}
								options={[
									{ value: 'all', label: 'Все разделы' },
									...sections.map((value) => ({ value, label: value })),
								]}
							/>
						</label>
					)}
					<label>
						Порядок
						<Select
							aria-label="Сортировка сметы"
							value={sort}
							onChange={setSort}
							options={sortOptions}
						/>
					</label>
					<small>
						Объёмные работы, трудозатраты и прочие позиции разделены по единицам измерения.
						Перерасход расположен в конце списка.
					</small>
				</div>
			</Modal>
		</section>
	);
}
