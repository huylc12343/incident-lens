type Props = {
  value: string;
  error: string;
  onChange: (value: string) => void;
};
export function TimestampInput({ value, error, onChange }: Props) {
  return (
    <section className="timestamp-section">
      <div>
        <h2>Recorded Disengagement</h2>
        <p>Provide the timestamp associated with the recorded event.</p>
      </div>
      <div className="timestamp-field">
        <label htmlFor="event-timestamp">
          Event timestamp <span>*</span>
        </label>
        <input
          id="event-timestamp"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="00:03:45.200"
          inputMode="numeric"
          aria-describedby="timestamp-help timestamp-error"
          aria-invalid={Boolean(error)}
        />
        <p id="timestamp-help">
          Timestamp provided by the recorded event. VLens does not detect the
          disengagement in this MVP.
        </p>
        {error && (
          <p id="timestamp-error" className="field-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
