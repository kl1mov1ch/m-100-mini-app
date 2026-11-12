import { Button, Empty, Input, Tag } from 'antd';
import { ChevronRight, Search, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import type { WorkspaceView } from '../App';
import { Money, unit } from '../lib/format';
import type { Position } from '../types';
import { BitrixReadStatus } from './BitrixReadStatus';
import { estimateStatus, formatVolume, positionOverrun } from '../lib/position-volume';

export function ObjectCatalogue({
	workspace,
	onView,
}: {
	workspace: WorkspaceView;
	onView: (position: Position) => void;
}) {
	const [query, setQuery] = useState('');
	const { allPositions, positions, openObjectSection } = workspace;
	const term = query.trim().toLocaleLowerCase('ru');
	const matching = allPositions
		.filter((position) =>
			[position.name, position.section, position.source_sheet]
				.filter(Boolean)
				.join(' ')
				.toLocaleLowerCase('ru')
				.includes(term),
		)
		.sort((left, right) => Number(!!positionOverrun(left)) - Number(!!positionOverrun(right)));
	if (!allPositions.length) {
		return (
			<section className="object-panel">
				<Empty description="Смета пуста" image={Empty.PRESENTED_IMAGE_SIMPLE} />
				<Button type="primary" onClick={() => openObjectSection('table')}>
					Добавить таблицу
				</Button>
			</section>
		);
	}
	return (
		<section className="object-panel">
			<div className="object-panel-heading">
				<h2>Смета</h2>
			</div>
			<BitrixReadStatus workspace={workspace} />
			<Input
				aria-label="Найти работу в смете"
				placeholder="Название работы"
				prefix={<Search size={17} />}
				allowClear
				value={query}
				onChange={(event) => setQuery(event.target.value)}
			/>

			{!matching.length && (
				<Empty description="Работы не найдены" image={Empty.PRESENTED_IMAGE_SIMPLE} />
			)}
			<ul className="object-catalogue">
				{matching.map((position) => {
					const overrun = positionOverrun(position);
					const values = overrun || position.bitrix || position;
					return (
						<li key={position.id} className={overrun ? 'catalogue-overrun' : undefined}>
							<button type="button" className="catalogue-position" onClick={() => onView(position)}>
								<b>{position.name}</b>
								{overrun && (
									<>
										<span className="catalogue-overrun-label">
											<TriangleAlert size={14} aria-hidden />
											{overrun.completed > overrun.planned
												? estimateStatus(overrun, position.unit)
												: 'Проверьте остаток'}
										</span>
										<small className="catalogue-volumes">
											<span>
												По смете <strong>{formatVolume(values.planned, position.unit)}</strong>
											</span>
											<span>
												Выполнено <strong>{formatVolume(values.completed, position.unit)}</strong>
											</span>
										</small>
									</>
								)}
								{!overrun && (
									<>
										<small>
											План {formatVolume(values.planned, position.unit)} · Выполнено{' '}
											{formatVolume(values.completed, position.unit)} ·{' '}
											{estimateStatus(values, position.unit)}
										</small>
										<small>
											<Money value={values.rate} /> / {unit(position.unit)}
										</small>
									</>
								)}
								{position.hidden && <Tag className="status-tag-attention">Скрыта из подбора</Tag>}
								<ChevronRight className="catalogue-position-arrow" size={17} />
							</button>
						</li>
					);
				})}
			</ul>
			{positions.length > 0 && !workspace.active?.work_dates?.length && (
				<Button type="primary" onClick={() => openObjectSection('reports')}>
					Заполнить первый отчёт
				</Button>
			)}
		</section>
	);
}
