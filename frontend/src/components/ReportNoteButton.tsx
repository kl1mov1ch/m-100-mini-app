import { Button, Modal } from 'antd';
import { MessageSquareText } from 'lucide-react';
import { useState } from 'react';
import { NoteInput } from './NoteInput';

export function ReportNoteButton({
	project,
	scope,
	label,
	value,
	onChange,
	maxLength,
}: {
	project: string;
	scope: string;
	label: string;
	value: string;
	onChange: (value: string) => void;
	maxLength?: number;
}) {
	const [open, setOpen] = useState(false);
	const [draft, setDraft] = useState('');
	return (
		<>
			<Button
				className="report-note-button"
				aria-label={label + (value.trim() ? ', заполнено' : '')}
				aria-haspopup="dialog"
				data-filled={!!value.trim()}
				icon={<MessageSquareText size={16} aria-hidden />}
				onClick={() => {
					setDraft(value);
					setOpen(true);
				}}
			>
				Примечание
			</Button>
			<Modal
				className="report-note-editor"
				title={label}
				open={open}
				destroyOnHidden
				okText="Применить"
				footer={(_, { OkBtn }) => <OkBtn />}
				onCancel={() => setOpen(false)}
				onOk={() => {
					onChange(draft);
					setOpen(false);
				}}
			>
				<NoteInput
					project={project}
					scope={scope}
					value={draft}
					onChange={setDraft}
					label={label}
					maxLength={maxLength}
				/>
			</Modal>
		</>
	);
}
