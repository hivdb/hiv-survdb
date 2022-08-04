CREATE FUNCTION patientShouldFromSameCountry(dname varchar, iname varchar, ccode char(3)) RETURNS boolean AS $$
  SELECT NOT EXISTS (
    SELECT 1 FROM isolates WHERE
      dataset_name = dname AND
      isolate_name = iname AND
      country_code != ccode
  )
$$ LANGUAGE SQL;

ALTER TABLE isolates ADD CONSTRAINT patient_should_from_same_country CHECK (
  patientShouldFromSameCountry(dataset_name, isolate_name, country_code)
);
