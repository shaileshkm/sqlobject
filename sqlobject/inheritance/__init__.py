from sqlobject import sqlbuilder
from sqlobject import classregistry
from sqlobject.main import SQLObject, SelectResults, True, False, makeProperties, getterName, setterName
import iteration


try:
    basestring
except NameError: # Python 2.2
    import types
    basestring = (types.StringType, types.UnicodeType)


class InheritableSelectResults(SelectResults):
    IterationClass = iteration.InheritableIteration

    def __init__(self, sourceClass, clause, clauseTables=None,
                 **ops):
        if clause is None or isinstance(clause, str) and clause == 'all':
            clause = sqlbuilder.SQLTrueClause
        tablesDict = sqlbuilder.tablesUsedDict(clause)
        tablesDict[sourceClass.sqlmeta.table] = 1
        orderBy = ops.get('orderBy')
        if orderBy and not isinstance(orderBy, basestring):
            tablesDict.update(sqlbuilder.tablesUsedDict(orderBy))
        #DSM: if this class has a parent, we need to link it
        #DSM: and be sure the parent is in the table list.
        #DSM: The following code is before clauseTables
        #DSM: because if the user uses clauseTables
        #DSM: (and normal string SELECT), he must know what he wants
        #DSM: and will do himself the relationship between classes.
        if type(clause) is not str:
            tableRegistry = {}
            allClasses = classregistry.registry(
                sourceClass.sqlmeta.registry).allClasses()
            for registryClass in allClasses:
                if registryClass.sqlmeta.table in tablesDict:
                    #DSM: By default, no parents are needed for the clauses
                    tableRegistry[registryClass] = registryClass
            for registryClass in allClasses:
                if registryClass.sqlmeta.table in tablesDict:
                    currentClass = registryClass
                    while currentClass._parentClass:
                        currentClass = currentClass._parentClass
                        if tableRegistry.has_key(currentClass):
                            #DSM: Must keep the last parent needed
                            #DSM: (to limit the number of join needed)
                            tableRegistry[registryClass] = currentClass
                            #DSM: Remove this class as it is a parent one
                            #DSM: of a needed children
                            del tableRegistry[currentClass]
            #DSM: Table registry contains only the last children
            #DSM: or standalone classes
            parentClause = []
            for (currentClass, minParentClass) in tableRegistry.items():
                while currentClass != minParentClass and currentClass._parentClass:
                    parentClass = currentClass._parentClass
                    parentClause.append(currentClass.q.id == parentClass.q.id)
                    currentClass = parentClass
                    tablesDict[currentClass.sqlmeta.table] = 1
            clause = reduce(sqlbuilder.AND, parentClause, clause)

        super(InheritableSelectResults, self).__init__(sourceClass, clause, clauseTables,
                 **ops)


class InheritableSQLObject(SQLObject):
    SelectResultsClass = InheritableSelectResults

    def get(cls, id, connection=None, selectResults=None, childResults=None, childUpdate=False):

        val = super(InheritableSQLObject, cls).get(id, connection, selectResults)

        #DSM: If we are updating a child, we should never return a child...
        if childUpdate: return val
        #DSM: If this class has a child, return the child
        if hasattr(val, 'childName'):
             childName = val.childName
             if childName is not None:
                 return val._childClasses[childName].get(id, selectResults=childResults)
        #DSM: Now, we know we are alone or the last child in a family...
        #DSM: It's time to find our parents
        inst = val
        while inst._parentClass and not inst._parent:
            inst._parent = inst._parentClass.get(id, childUpdate=True)
            inst = inst._parent
        #DSM: We can now return ourself
        return val

    get = classmethod(get)

    def addColumn(cls, columnDef, changeSchema=False, connection=None, childUpdate=False):
        #DSM: Try to add parent properties to the current class
        #DSM: Only do this once if possible at object creation and once for
        #DSM: each new dynamic column to refresh the current class
        if childUpdate or cls._parentClass:
            for col in cls._parentClass._columns:
                cname = col.name
                if cname == 'childName': continue
                setattr(cls, getterName(cname), eval(
                    'lambda self: self._parent.%s' % cname))
                if not col.kw.has_key('immutable') or not col.kw['immutable']:
                    setattr(cls, setterName(cname), eval(
                        'lambda self, val: setattr(self._parent, %s, val)'
                        % repr(cname)))
            if childUpdate:
                makeProperties(cls)
                return

        super(InheritableSQLObject, cls).addColumn(columnDef, changeSchema, connection)

        #DSM: Update each child class if needed and existing (only for new
        #DSM: dynamic column as no child classes exists at object creation)
        for c in cls._childClasses.values():
            c.addColumn(columnDef, childUpdate=True)

    addColumn = classmethod(addColumn)

    def delColumn(cls, column, changeSchema=False, connection=None):
        super(InheritableSQLObject, cls).delColumn(column, changeSchema, connection)

        #DSM: Update each child class if needed
        #DSM: and delete properties for this column
        for c in cls._childClasses.values():
            delattr(c, name)

    delColumn = classmethod(delColumn)

    def addJoin(cls, joinDef, childUpdate=False):
        #DSM: Try to add parent properties to the current class
        #DSM: Only do this once if possible at object creation and once for
        #DSM: each new dynamic join to refresh the current class
        if childUpdate or cls._parentClass:
            for jdef in cls._parentClass._joins:
                join = jdef.withClass(cls)
                jname = join.joinMethodName
                jarn  = join.addRemoveName
                setattr(cls, getterName(jname),
                    eval('lambda self: self._parent.%s' % jname))
                if hasattr(join, 'remove'):
                    setattr(cls, 'remove' + jarn,
                        eval('lambda self,o: self._parent.remove%s(o)' % jarn))
                if hasattr(join, 'add'):
                    setattr(cls, 'add' + jarn,
                        eval('lambda self,o: self._parent.add%s(o)' % jarn))
            if childUpdate:
                makeProperties(cls)
                return

        super(InheritableSQLObject, cls).addJoin(joinDef)

        #DSM: Update each child class if needed and existing (only for new
        #DSM: dynamic join as no child classes exists at object creation)
        for c in cls._childClasses.values():
            c.addJoin(joinDef, childUpdate=True)

    addJoin = classmethod(addJoin)

    def delJoin(cls, joinDef):
        super(InheritableSQLObject, cls).delJoin(joinDef)

        #DSM: Update each child class if needed
        #DSM: and delete properties for this join
        for c in cls._childClasses.values():
            delattr(c, meth)

    delJoin = classmethod(delJoin)

    def _create(self, id, **kw):

        #DSM: If we were called by a children class,
        #DSM: we must retreive the properties dictionary.
        #DSM: Note: we can't use the ** call paremeter directly
        #DSM: as we must be able to delete items from the dictionary
        #DSM: (and our children must know that the items were removed!)
        if kw.has_key('kw'):
            kw = kw['kw']
        #DSM: If we are the children of an inheritable class,
        #DSM: we must first create our parent
        if self._parentClass:
            parentClass = self._parentClass
            new_kw = {}
            parent_kw = {}
            for (name, value) in kw.items():
                    if hasattr(parentClass, name):
                        parent_kw[name] = value
                    else:
                        new_kw[name] = value
            kw = new_kw
            self._parent = parentClass(kw=parent_kw)
            self._parent.childName = self.__class__.__name__
            id = self._parent.id

        super(InheritableSQLObject, self)._create(id, **kw)

    def destroySelf(self):
        #DSM: If this object has parents, recursivly kill them
        if hasattr(self, '_parent') and self._parent:
            self._parent.destroySelf()
        super(InheritableSQLObject, self).destroySelf()


__all__ = ['InheritableSQLObject']