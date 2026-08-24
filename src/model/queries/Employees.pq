let
    Supplied = Text.Trim(DataFolderPath),
    Normalised = Text.Replace(Supplied, "/", "\"),
    FolderPath =
        if Text.EndsWith(Normalised, "\") then
            Text.Start(Normalised, Text.Length(Normalised) - 1)
        else
            Normalised,
    FilePath = FolderPath & "\" & "Contoso-Entra-Users-RAW.csv",
    Source = Csv.Document(
        File.Contents(FilePath),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Kept = Table.SelectColumns(
        Headers,
        {
            "userPrincipalName",
            "DisplayName",
            "JobTitle",
            "department",
            "employeeType",
            "city",
            "Country",
            "accountEnabled",
            "HasLicense"
        }
    ),
    Renamed = Table.RenameColumns(
        Kept,
        {
            {"userPrincipalName", "User Principal Name"},
            {"DisplayName", "Display Name"},
            {"JobTitle", "Job Title"},
            {"department", "Department"},
            {"employeeType", "Employee Type"},
            {"city", "City"},
            {"accountEnabled", "Account Enabled Raw"},
            {"HasLicense", "Has License Raw"}
        }
    ),
    Typed = Table.TransformColumnTypes(
        Renamed,
        {
            {"User Principal Name", type text},
            {"Display Name", type text},
            {"Job Title", type text},
            {"Department", type text},
            {"Employee Type", type text},
            {"City", type text},
            {"Country", type text},
            {"Account Enabled Raw", type text},
            {"Has License Raw", type text}
        }
    ),
    Trimmed = Table.TransformColumns(
        Typed,
        {
            {"Department", Text.Trim, type text},
            {"Country", Text.Trim, type text},
            {"City", Text.Trim, type text},
            {"Job Title", Text.Trim, type text},
            {"Employee Type", Text.Trim, type text}
        }
    ),
    AddIsLicensed = Table.AddColumn(
        Trimmed,
        "Is Licensed",
        each Text.Upper(Text.Trim(if [Has License Raw] = null then "" else [Has License Raw])) = "TRUE",
        type logical
    ),
    AddLicenseStatus = Table.AddColumn(
        AddIsLicensed,
        "License Status",
        each if [Is Licensed] then "Copilot licensed" else "Not licensed",
        type text
    ),
    AddAccountEnabled = Table.AddColumn(
        AddLicenseStatus,
        "Account Enabled",
        each Text.Upper(Text.Trim(if [Account Enabled Raw] = null then "" else [Account Enabled Raw])) = "TRUE",
        type logical
    ),
    Employees = Table.RemoveColumns(AddAccountEnabled, {"Has License Raw", "Account Enabled Raw"})
in
    Employees
