import Foundation

public enum PowerSourcePresentation {
    public static func name(_ value: String?) -> String? {
        guard let value else { return nil }
        let name = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, name.count <= 64, name.utf8.count <= 160 else { return nil }

        let rejectedCategories: Set<Unicode.GeneralCategory> = [
            .control, .format, .lineSeparator, .paragraphSeparator,
        ]
        guard !name.unicodeScalars.contains(where: { rejectedCategories.contains($0.properties.generalCategory) }) else {
            return nil
        }
        return name
    }
}
