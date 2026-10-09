"""Read-only checks for the fictional Alex Morgan bank-statement fixture.

Run inside the HomeFlow backend container; see Document_Workflow_Test.md.
This verifies an existing upload. It does not upload or modify documents.
"""
import argparse
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from uuid import UUID, uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file-id', required=True, type=UUID)
    parser.add_argument('--customer-id', required=True, type=UUID)
    parser.add_argument('--application-id', required=True, type=UUID)
    parser.add_argument('--expected-correction', required=True,
                        help='Exact institution wording saved using the review screen')
    args = parser.parse_args()

    import ollama
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.db.session import engine
    from app.api.v1.chat import _retrieve, EMBED_MODEL

    failures = []

    def check(label, condition):
        print(('PASS: ' if condition else 'FAIL: ') + label, flush=True)
        if not condition:
            failures.append(label)

    def money(value):
        try:
            return Decimal(str(value).replace('$', '').replace(',', '').strip())
        except InvalidOperation:
            return None

    params = {'file_id': args.file_id, 'customer_id': args.customer_id,
              'application_id': args.application_id}
    with Session(engine) as session:
        try:
            # PostgreSQL rejects any accidental writes in this transaction.
            session.execute(text('SET TRANSACTION READ ONLY'))
            file = session.execute(text('SELECT * FROM public.file WHERE file_id = :file_id'), params).mappings().one_or_none()
            check('sample file exists', file is not None)
            if file is None:
                return 1

            owner = session.execute(text('SELECT customer_id FROM public.application WHERE application_id = :application_id'), params).scalar_one_or_none()
            check('file and application belong to the expected customer',
                  file['customer_id'] == args.customer_id == owner
                  and file['application_id'] == args.application_id)
            check('completed bank-statement PDF with one page',
                  file['status'] == 'completed' and file['document_tag'] == 'bank_statement'
                  and file['content_type'] == 'application/pdf' and file['page_count'] == 1)
            key = file['storage_key'] or ''
            check('file metadata and flat storage key are populated',
                  bool(file['original_name']) and (file['size_bytes'] or 0) > 0
                  and bool(file['checksum']) and bool(key)
                  and not any(char in key for char in ('/', '\\', ':'))
                  and bool(file['logical_path']) and file['uploaded_at'] is not None)
            check('processing finished without a recorded error',
                  file['processed_at'] is not None and not file['error_detail']
                  and file['attempts'] >= 1)

            # Check the same bytes within this customer/application, not all customers.
            count = session.execute(text('''SELECT count(*) FROM public.file
                WHERE customer_id = :customer_id AND application_id = :application_id
                AND checksum = :checksum'''), {**params, 'checksum': file['checksum']}).scalar_one()
            check('one record for these file bytes in this application', count == 1)

            rows = session.execute(text('SELECT * FROM public.extraction WHERE file_id = :file_id'), params).mappings().all()
            expected_text = {'account_holder': 'Alex Morgan', 'institution': 'Demo Learning Bank',
                             'account_mask': '****0001', 'period_start': '2026-09-01',
                             'period_end': '2026-09-30'}
            expected_money = {'beginning_balance': '4000', 'ending_balance': '5000',
                              'total_deposits': '2000', 'total_withdrawals': '1000'}
            expected_names = set(expected_text) | set(expected_money)
            fields = {row['field_name']: row for row in rows}
            check('exactly nine expected fields, with no duplicate field names',
                  len(rows) == 9 and set(fields) == expected_names)
            for name, expected in {**expected_text, **expected_money}.items():
                row = fields.get(name)
                actual = row['value_raw'] if row else None
                matches = (money(actual) == Decimal(expected) if name in expected_money
                           else actual == expected)
                check('original extracted value: ' + name, row is not None and matches)
            check('all extracted fields have page-one evidence', bool(rows) and all(
                row['page'] == 1 and bool((row['evidence_quote'] or '').strip()) for row in rows))
            institution = fields.get('institution')
            check('institution correction is saved separately from the original',
                  institution is not None and institution['review_state'] == 'corrected'
                  and institution['corrected_value'] == args.expected_correction
                  and institution['value_raw'] == 'Demo Learning Bank'
                  and args.expected_correction != institution['value_raw'])

            chunks = session.execute(text('''SELECT customer_id, page, content,
                vector_dims(embedding) AS dimensions FROM public.document_chunk
                WHERE file_id = :file_id'''), params).mappings().all()
            check('document chunks contain text and 768-dimensional embeddings', bool(chunks) and all(
                row['dimensions'] == 768 and bool(row['content'].strip()) for row in chunks))
            check('all chunks have the expected customer and source page', bool(chunks) and all(
                row['customer_id'] == args.customer_id and row['page'] == 1 for row in chunks))

            # Exercise the backend's actual retrieval function, including its NULL branch.
            vector = ollama.embed(model=EMBED_MODEL, text='What is the closing balance in the bank statement?')
            customer = SimpleNamespace(customer_id=args.customer_id)
            for application, label in ((str(args.application_id), 'application search'),
                                       (None, 'customer-wide search')):
                results = _retrieve(session, customer, vector, application)
                check(label + ' returns the sample and source page', any(
                    item['file_id'] == str(args.file_id) and item['page'] == 1 for item in results))

            # An unused ID simulates a different caller without adding a customer.
            other_id = uuid4()
            while session.execute(text('SELECT 1 FROM public.customer WHERE customer_id = :id'), {'id': other_id}).scalar():
                other_id = uuid4()
            other = SimpleNamespace(customer_id=other_id)
            for application, label in ((str(args.application_id), 'with application filter'),
                                       (None, 'without application filter')):
                check('unused customer ID retrieves nothing ' + label,
                      _retrieve(session, other, vector, application) == [])
        except Exception as exc:
            # Do not dump SQL parameters, embeddings, credentials or document contents.
            print('ERROR: test could not finish (' + type(exc).__name__ + ').', flush=True)
            print('Check service logs, model availability and the backend search query.')
            return 1
        finally:
            session.rollback()

    print(f'Finished: {len(failures)} failed checks. No database records changed.')
    print('Scope: one fictional fixture and direct retrieval; not API authorization or AI answer validation.')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
