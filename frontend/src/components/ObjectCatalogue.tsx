import { Button, Empty, Input, Modal, Select } from 'antd';
import { ChevronDown, Search, SlidersHorizontal } from 'lucide-react';
import { useMemo, useState } from 'react';
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
import { CompactRow } from './CompactRow';

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
	const excess = positions.filter((position) => catalogueStatusMatches(position, 'overrun')).length;
	return (
		<section className="catalogue-group">
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
						{positions.map((position) => {
							const values = catalogueValues(position);
							const overrun = positionOverrun(position);
							const excess = overrun || values.completed > values.planned + 1e-8;
							return (
								<li key={position.id} className={excess ? 'catalogue-overrun' : undefined}>
									<CompactRow
										title={position.name}
										description={
											<>
												{formatVolume(values.completed, position.unit)} из{' '}
												{formatVolume(values.planned, position.unit)}
												{duplicateNames.has(position.name) &&
													' · ' +
														(position.source_sheet || position.section) +
														', стр. ' +
														position.source_row}
												{position.hidden && ' · скрыта'}
											</>
										}
										value={
											<>
												<Money value={values.rate} /> / {unit(position.unit)}
											</>
										}
										meta={
											excess && values.completed <= values.planned
												? 'Проверьте остаток'
												: estimateStatus(values, position.unit)
										}
										attention={!!excess}
										onClick={() => onView(position)}
									/>
								</li>
							);
						})}
					</ul>
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
						initiallyOpen
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
